"""End-to-end integration and launch verification test suite (Milestone M6, ADR 0029)."""

from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.db.session import get_session
from gst_copilot.embeddings import FakeEmbedder, get_embedder
from gst_copilot.observe.store import get_ask_recorder
from gst_copilot.rag.retriever import RetrievedChunk
from gst_copilot.rag.service import AskResult


@pytest.fixture
def app() -> FastAPI:
    from gst_copilot.api import health

    async def fake_ok() -> None:
        pass

    async def no_session() -> AsyncIterator[None]:
        yield None

    health.CHECKS = {"postgres": fake_ok, "redis": fake_ok}
    application = create_app()
    application.dependency_overrides[get_ask_recorder] = lambda: None
    application.dependency_overrides[get_session] = no_session
    application.dependency_overrides[get_embedder] = lambda: FakeEmbedder(384)
    return application


async def test_security_headers_and_health(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "x-request-id" in r.headers
        assert r.json()["status"] == "ok"

        r_ready = await client.get("/ready")
        assert r_ready.status_code == 200
        data = r_ready.json()
        assert data["status"] == "ready"
        assert "corpus_date" in data
        assert "corpus_freshness_days" in data


async def test_invoice_check_workflow(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Valid invoice
        valid_inv = {
            "invoice_no": "INV-2026-001",
            "invoice_date": "2026-10-15",
            "supplier_gstin": "27AAPFU0939F1ZV",
            "recipient_gstin": "29ABCCE1234F1ZY",
            "place_of_supply": "29",
            "taxable_value": "10000.00",
            "igst": "1800.00",
            "cgst": "0.00",
            "sgst": "0.00",
            "invoice_total": "11800.00",
        }
        res = await client.post("/check-invoice", json=valid_inv)
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert all(c["ok"] for c in body["checks"])

        # Invalid total
        invalid_inv = dict(valid_inv, invoice_total="15000.00")
        res_inv = await client.post("/check-invoice", json=invalid_inv)
        assert res_inv.status_code == 200
        assert res_inv.json()["ok"] is False


async def test_reconciliation_and_gstr3b_workflow(app: FastAPI, tmp_path: Path) -> None:
    from gst_copilot.recon import synth
    from gst_copilot.recon.csvio import write_invoices

    books, twob, _ = synth.generate(seed=1, invoices=10)
    b_path = tmp_path / "books.csv"
    g_path = tmp_path / "gstr2b.csv"
    write_invoices(b_path, books, "books")
    write_invoices(g_path, twob, "gstr2b")

    files = {
        "purchase_register": ("books.csv", b_path.read_bytes(), "text/csv"),
        "gstr2b": ("gstr2b.csv", g_path.read_bytes(), "text/csv"),
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/reconcile", files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["books_rows"] == len(books)
        assert data["gstr2b_rows"] == len(twob)
        assert data["draft_3b"] is not None
        draft = data["draft_3b"]
        assert "a5_all_other_itc" in draft
        assert "c_net_itc" in draft
        assert "b2_temporary_reversals" in draft
        assert "d1_reclaimed" in draft
        assert "d2_ineligible" in draft


async def test_date_aware_ask_and_feedback_workflow(app: FastAPI) -> None:
    fake_chunk = RetrievedChunk(
        doc_id="CIRC-170-2022",
        title="Circular No. 170/02/2022-GST",
        source_url="https://cbic-gst.gov.in/pdf/Circular-170-02-2022-GST.pdf",
        chunk_index=1,
        text="Para 4.3: Table 4(A)(5) auto-population details.",
        score=0.92,
        section="4.3",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("gst_copilot.api.ask.ask", new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = AskResult(
                mode="retrieval_only",
                answer=None,
                retrieved=[fake_chunk],
                context=[fake_chunk],
                as_of=date(2022, 7, 10),
            )

            res = await client.post(
                "/ask",
                json={
                    "question": "How are temporary reversals reported in GSTR-3B?",
                    "as_of": "2022-07-10",
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["as_of"] == "2022-07-10"
            assert len(data["passages"]) == 1
            assert data["passages"][0]["doc_id"] == "CIRC-170-2022"


async def test_unhandled_exception_returns_json_error(app: FastAPI) -> None:
    @app.get("/test-internal-error")
    async def buggy_route() -> None:
        raise RuntimeError("simulated unexpected crash")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        res = await client.get("/test-internal-error")
        assert res.status_code == 500
        data = res.json()
        assert data["detail"] == "An internal server error occurred."
        assert "request_id" in data
        assert "x-request-id" in res.headers
