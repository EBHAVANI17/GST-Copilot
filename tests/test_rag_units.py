import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.db.session import get_session
from gst_copilot.embeddings import FakeEmbedder, get_embedder
from gst_copilot.evals.golden import load_golden
from gst_copilot.evals.metrics import (
    first_relevant_rank,
    hit_at_k,
    mean_reciprocal_rank,
    percentile,
)
from gst_copilot.rag import service
from gst_copilot.rag.llm import LLMError, OpenAICompatibleClient, get_llm
from gst_copilot.rag.prompt import REFUSAL, build_messages, cited_refs, is_refusal
from gst_copilot.rag.retriever import RetrievedChunk

CHUNKS = [
    RetrievedChunk("SAMPLE-ACT", "Act", "https://x/act", 0, "apply within thirty days", 0.9),
    RetrievedChunk("SAMPLE-RULES", "Rules", "https://x/rules", 2, "credit statement", 0.5),
]


# ---------- prompt ----------


def test_prompt_contains_tagged_context_and_rules() -> None:
    msgs = build_messages("When to register?", CHUNKS)
    assert msgs[0]["role"] == "system" and REFUSAL in msgs[0]["content"]
    assert "[SAMPLE-ACT#0]" in msgs[1]["content"]
    assert "When to register?" in msgs[1]["content"]


def test_citations_are_extracted_once_in_order() -> None:
    text = "Apply in 30 days [SAMPLE-ACT#0]. Also [SAMPLE-RULES#2] and [SAMPLE-ACT#0]."
    assert cited_refs(text) == ["SAMPLE-ACT#0", "SAMPLE-RULES#2"]


def test_refusal_detection() -> None:
    assert is_refusal(REFUSAL)
    assert not is_refusal("Apply within thirty days [SAMPLE-ACT#0].")


# ---------- metrics ----------


def test_rank_hit_and_mrr() -> None:
    assert first_relevant_rank(["A", "B", "C"], {"C"}) == 3
    assert first_relevant_rank(["A"], {"Z"}) is None
    ranks = [1, 3, None, 2]
    assert hit_at_k(ranks, 1) == 0.25
    assert hit_at_k(ranks, 3) == 0.75
    assert mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)


def test_percentile_nearest_rank() -> None:
    assert percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 95) == 100
    assert percentile([10, 20, 30, 40], 50) == 20


def test_golden_file_validation(tmp_path: Path) -> None:
    good = Path(__file__).parent / "fixtures" / "sample_corpus" / "golden.jsonl"
    assert len(load_golden(good)) == 4
    bad = tmp_path / "g.jsonl"
    bad.write_text(json.dumps({"id": "x", "question": "q?", "type": "lookup"}) + "\n")
    with pytest.raises(ValueError, match="expected_doc_ids"):
        load_golden(bad)


def test_golden_expected_sections(tmp_path: Path) -> None:
    base = {"question": "q?", "type": "lookup", "expected_doc_ids": ["A"]}
    path = tmp_path / "g.jsonl"
    path.write_text(json.dumps({"id": "a", **base, "expected_sections": [16, "17A"]}) + "\n")
    assert load_golden(path)[0].expected_sections == ["16", "17A"]

    path.write_text(json.dumps({"id": "b", **base, "expected_sections": ["16(2)"]}) + "\n")
    with pytest.raises(ValueError, match="section numbers only"):
        load_golden(path)

    unanswerable = {"id": "c", "question": "q?", "type": "unanswerable", "expected_sections": ["1"]}
    path.write_text(json.dumps(unanswerable) + "\n")
    with pytest.raises(ValueError, match="expected_sections"):
        load_golden(path)


# ---------- LLM client against a fake HTTP server ----------


def fake_openai(answer: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["temperature"] == 0
        return httpx.Response(
            status,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": answer}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 15},
            },
        )

    return httpx.MockTransport(handler)


async def test_llm_client_parses_openai_response() -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "test-model", transport=fake_openai("hi"))
    out = await llm.complete([{"role": "user", "content": "x"}])
    assert (out.text, out.model, out.prompt_tokens) == ("hi", "test-model", 120)


async def test_llm_client_wraps_http_errors() -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_openai("", status=500))
    with pytest.raises(LLMError):
        await llm.complete([{"role": "user", "content": "x"}])


# ---------- /ask endpoint with fakes (no database, no real LLM) ----------


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    async def fake_search(
        session: Any, qvec: list[float], k: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        return CHUNKS[:k]

    async def no_session() -> AsyncIterator[None]:
        yield None

    monkeypatch.setattr(service, "search", fake_search)
    app = create_app()
    app.dependency_overrides[get_session] = no_session
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(384)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


async def test_ask_retrieval_only_mode_without_llm(client: AsyncClient) -> None:
    client.app.dependency_overrides[get_llm] = lambda: None  # type: ignore[attr-defined]
    r = await client.post("/ask", json={"question": "When must I register?"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "retrieval_only" and body["answer"] is None
    assert [p["ref"] for p in body["passages"]] == ["SAMPLE-ACT#0", "SAMPLE-RULES#2"]


async def test_ask_generated_answer_marks_cited_and_invalid(client: AsyncClient) -> None:
    answer = "Apply within thirty days [SAMPLE-ACT#0]. See also [MADE-UP#9]."
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_openai(answer))
    client.app.dependency_overrides[get_llm] = lambda: llm  # type: ignore[attr-defined]
    body = (await client.post("/ask", json={"question": "When must I register?"})).json()
    assert body["mode"] == "generated"
    assert {p["ref"]: p["cited"] for p in body["passages"]} == {
        "SAMPLE-ACT#0": True,
        "SAMPLE-RULES#2": False,
    }
    assert body["invalid_citations"] == ["MADE-UP#9"]
    assert body["disclaimer"] == "Information, not tax advice."


async def test_ask_returns_502_when_llm_fails(client: AsyncClient) -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_openai("", status=503))
    client.app.dependency_overrides[get_llm] = lambda: llm  # type: ignore[attr-defined]
    r = await client.post("/ask", json={"question": "When must I register?"})
    assert r.status_code == 502


async def test_ask_validates_input(client: AsyncClient) -> None:
    client.app.dependency_overrides[get_llm] = lambda: None  # type: ignore[attr-defined]
    assert (await client.post("/ask", json={"question": "?"})).status_code == 422
    assert (await client.post("/ask", json={"question": "ok?", "top_k": 99})).status_code == 422
