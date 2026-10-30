"""POST /reconcile: uploads, JSON and CSV results, clear errors."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.recon import synth
from gst_copilot.recon.csvio import BOOKS_COLUMNS, write_invoices


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c


@pytest.fixture
def files(tmp_path: Path) -> dict[str, tuple[str, bytes, str]]:
    books, twob, _ = synth.generate(seed=1, invoices=80)
    write_invoices(tmp_path / "b.csv", books, "books")
    write_invoices(tmp_path / "g.csv", twob, "gstr2b")
    return {
        "purchase_register": ("b.csv", (tmp_path / "b.csv").read_bytes(), "text/csv"),
        "gstr2b": ("g.csv", (tmp_path / "g.csv").read_bytes(), "text/csv"),
    }


async def test_json_result_has_a_summary_and_every_invoice(
    client: AsyncClient, files: dict[str, tuple[str, bytes, str]]
) -> None:
    r = await client.post("/reconcile", files=files)
    assert r.status_code == 200
    body = r.json()
    books, twob, expected = synth.generate(seed=1, invoices=80)
    assert (body["books_rows"], body["gstr2b_rows"]) == (len(books), len(twob))
    assert sum(body["summary"].values()) == len(body["results"]) == len(expected)
    assert body["tolerance_rupees"] == "1.00"
    assert set(body["tax_by_label"]) == set(body["summary"])
    assert set(body["explanations"]) == set(body["summary"])
    for exp in body["explanations"].values():
        assert {"title", "explanation", "action", "gstr3b_row", "citation"} <= set(exp)
    first = body["results"][0]
    assert {"label", "supplier_gstin", "invoice_no", "total_tax", "details"} <= set(first)


async def test_csv_download(client: AsyncClient, files: dict[str, tuple[str, bytes, str]]) -> None:
    r = await client.post("/reconcile?format=csv&tolerance=0", files=files)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "reconciliation.csv" in r.headers["content-disposition"]
    assert r.text.splitlines()[0] == "books_id,gstr2b_id,label,details"


async def test_tolerance_zero_turns_rounding_into_amount_differences(
    client: AsyncClient, files: dict[str, tuple[str, bytes, str]]
) -> None:
    loose = (await client.post("/reconcile", files=files)).json()["summary"]
    strict = (await client.post("/reconcile?tolerance=0", files=files)).json()["summary"]
    assert strict["amount_diff"] > loose["amount_diff"]


async def test_bad_rows_and_files_get_clear_errors(
    client: AsyncClient, files: dict[str, tuple[str, bytes, str]]
) -> None:
    bad = ",".join(BOOKS_COLUMNS) + "\nR1,X,Y,1,01/04/2026,100,0,0,0,2026-04\n"
    r = await client.post(
        "/reconcile", files={**files, "purchase_register": ("mine.csv", bad.encode(), "text/csv")}
    )
    assert r.status_code == 422 and "mine.csv line 2: invoice_date" in r.json()["detail"]

    r = await client.post(
        "/reconcile", files={**files, "gstr2b": ("x.csv", b"\xff\xfe\x00bad", "text/csv")}
    )
    assert r.status_code == 422 and "UTF-8" in r.json()["detail"]

    r = await client.post("/reconcile", files={"gstr2b": files["gstr2b"]})
    assert r.status_code == 422  # purchase register missing


async def test_large_files_are_refused(
    client: AsyncClient, files: dict[str, tuple[str, bytes, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gst_copilot.api import reconcile

    monkeypatch.setattr(reconcile, "MAX_BYTES", 100)
    r = await client.post("/reconcile", files=files)
    assert r.status_code == 413 and "larger than" in r.json()["detail"]


async def test_too_many_rows_are_refused(
    client: AsyncClient, files: dict[str, tuple[str, bytes, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gst_copilot.api import reconcile

    monkeypatch.setattr(reconcile, "MAX_ROWS", 10)
    r = await client.post("/reconcile", files=files)
    assert r.status_code == 413 and "b.csv: over 10 rows" in r.json()["detail"]
