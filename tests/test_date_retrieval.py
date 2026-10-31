"""Unit tests for date-aware retrieval (Milestone M5, ADR 0028)."""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from gst_copilot.api.ask import AskRequest
from gst_copilot.api.main import create_app
from gst_copilot.evals.golden import load_golden
from gst_copilot.observe.store import get_ask_recorder
from gst_copilot.rag import service
from gst_copilot.rag.retriever import RetrievedChunk, _base


def test_ask_request_as_of_validation() -> None:
    req = AskRequest(question="Conditions for taking input tax credit?", as_of=date(2022, 7, 1))
    assert req.as_of == date(2022, 7, 1)

    req_none = AskRequest(question="Conditions for taking input tax credit?")
    assert req_none.as_of is None


def test_retriever_base_query_filters_dates() -> None:
    dummy_vec = [0.1] * 384

    # Without as_of: no effective_from / effective_to conditions
    stmt_unfiltered = _base(dummy_vec, as_of=None)
    compiled_unfiltered = str(stmt_unfiltered)
    assert "effective_from" not in compiled_unfiltered
    assert "effective_to" not in compiled_unfiltered

    # With as_of: filters effective_from <= as_of and effective_to >= as_of
    target = date(2021, 1, 1)
    stmt_filtered = _base(dummy_vec, as_of=target)
    compiled_filtered = str(stmt_filtered)
    assert "effective_from" in compiled_filtered
    assert "effective_to" in compiled_filtered


async def test_ask_service_passes_as_of() -> None:
    fake_chunk = RetrievedChunk(
        doc_id="CGST-ACT-2017",
        title="CGST Act",
        source_url="https://example.com",
        chunk_index=1,
        text="Section 16 text",
        score=0.95,
        section="16",
    )

    with (
        patch.object(service, "search", new_callable=AsyncMock) as mock_search,
        patch.object(service, "expand", new_callable=AsyncMock) as mock_expand,
    ):
        mock_search.return_value = [fake_chunk]
        mock_expand.return_value = [fake_chunk]
        fake_embedder = AsyncMock()
        fake_embedder.embed_query.return_value = [0.1] * 384

        result = await service.ask(
            question="What are conditions for taking ITC?",
            session=AsyncMock(),
            embedder=fake_embedder,
            llm=None,
            k=5,
            reranker=None,
            as_of=date(2021, 6, 1),
        )

        assert result.as_of == date(2021, 6, 1)
        mock_search.assert_called_once()
        _, kwargs = mock_search.call_args
        assert kwargs.get("as_of") == date(2021, 6, 1)


async def test_ask_endpoint_accepts_and_returns_as_of() -> None:
    fake_chunk = RetrievedChunk(
        doc_id="CGST-ACT-2017",
        title="CGST Act",
        source_url="https://example.com",
        chunk_index=1,
        text="Section 16 text",
        score=0.95,
        section="16",
    )

    app = create_app()
    app.dependency_overrides[get_ask_recorder] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with patch("gst_copilot.api.ask.ask", new_callable=AsyncMock) as mock_ask:
            mock_ask.return_value = service.AskResult(
                mode="retrieval_only",
                answer=None,
                retrieved=[fake_chunk],
                context=[fake_chunk],
                as_of=date(2021, 6, 1),
            )

            response = await client.post(
                "/ask",
                json={
                    "question": "What are the conditions for ITC in 2021?",
                    "as_of": "2021-06-01",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["as_of"] == "2021-06-01"
            assert data["mode"] == "retrieval_only"


def test_golden_item_loads_as_of(tmp_path: Path) -> None:
    p = tmp_path / "test.jsonl"
    line = (
        '{"id": "q_date", "question": "What was the rate?", "type": "date", '
        '"expected_doc_ids": ["CGST-ACT-2017"], "as_of": "2020-03-31"}\n'
    )
    p.write_text(line, encoding="utf-8")
    items = load_golden(p)
    assert len(items) == 1
    assert items[0].as_of == date(2020, 3, 31)
