"""Streaming: the LLM client's SSE parsing, ask_stream events, POST /ask/stream."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from gst_copilot.api.main import create_app
from gst_copilot.client import parse_sse
from gst_copilot.db.models import AskLog
from gst_copilot.db.session import get_session
from gst_copilot.embeddings import FakeEmbedder, get_embedder
from gst_copilot.observe.report import build_report
from gst_copilot.observe.store import get_ask_recorder, to_row
from gst_copilot.rag import service
from gst_copilot.rag.llm import Completion, LLMError, OpenAICompatibleClient, get_llm
from gst_copilot.rag.rerank import get_reranker
from gst_copilot.rag.retriever import RetrievedChunk

CHUNKS = [
    RetrievedChunk("SAMPLE-ACT", "Act", "https://x/act", 0, "apply within thirty days", 0.9),
    RetrievedChunk("SAMPLE-RULES", "Rules", "https://x/rules", 2, "credit statement", 0.5),
]
PIECES = ["Apply ", "within thirty days ", "[SAMPLE-ACT#0]."]


def fake_stream(
    pieces: list[str], finish: str = "stop", status: int = 200, seen: dict[str, Any] | None = None
) -> httpx.MockTransport:
    """An OpenAI-compatible server that streams `pieces` as server-sent events."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.update(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text="down")
        events = [{"model": "m", "choices": [{"delta": {"role": "assistant"}}]}]
        events += [{"model": "m", "choices": [{"delta": {"content": p}}]} for p in pieces]
        events.append({"model": "m", "choices": [{"delta": {}, "finish_reason": finish}]})
        events.append(
            {"model": "m", "choices": [], "usage": {"prompt_tokens": 90, "completion_tokens": 7}}
        )
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=": keep-alive\n\n" + body,
                              headers={"content-type": "text/event-stream"})  # fmt: skip

    return httpx.MockTransport(handler)


# ---------- LLM client ----------


async def test_stream_yields_pieces_then_a_completion() -> None:
    seen: dict[str, Any] = {}
    llm = OpenAICompatibleClient(
        "http://llm/v1", "m", max_tokens=64, transport=fake_stream(PIECES, "length", seen=seen)
    )
    out = [x async for x in llm.stream([{"role": "user", "content": "x"}])]
    assert out[:-1] == PIECES
    final = out[-1]
    assert isinstance(final, Completion)
    assert final.text == "".join(PIECES) and final.truncated
    assert (final.prompt_tokens, final.completion_tokens) == (90, 7)
    assert seen["stream"] is True and seen["stream_options"] == {"include_usage": True}
    assert seen["max_tokens"] == 64 and seen["temperature"] == 0


async def test_stream_wraps_http_errors() -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_stream([], status=503))
    with pytest.raises(LLMError):
        [x async for x in llm.stream([{"role": "user", "content": "x"}])]


# ---------- ask_stream ----------


@pytest.fixture
def no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(
        session: Any, qvec: list[float], k: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        return CHUNKS[:k]

    monkeypatch.setattr(service, "search", fake_search)


async def test_ask_stream_events_in_order(no_db: None) -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_stream(PIECES))
    events = [e async for e in service.ask_stream("q?", None, FakeEmbedder(384), llm, 2)]  # type: ignore[arg-type]
    first, *tokens, last = events
    assert isinstance(first, service.Retrieved) and first.result.answer is None
    assert [c.ref for c in first.result.context] == ["SAMPLE-ACT#0", "SAMPLE-RULES#2"]
    assert [t.text for t in tokens if isinstance(t, service.Token)] == PIECES
    assert isinstance(last, service.Answered)
    r = last.result
    assert r.answer == "".join(PIECES) and r.cited == ["SAMPLE-ACT#0"] and r.streamed
    assert 0 <= r.timings_ms["first_token"] <= r.timings_ms["generate"]


async def test_ask_stream_falls_back_for_a_client_that_cannot_stream(no_db: None) -> None:
    class Plain:
        async def complete(self, messages: list[dict[str, str]]) -> Completion:
            return Completion("Whole answer [SAMPLE-ACT#0].", "m", None, None)

    events = [e async for e in service.ask_stream("q?", None, FakeEmbedder(384), Plain(), 2)]  # type: ignore[arg-type]
    assert [type(e).__name__ for e in events] == ["Retrieved", "Token", "Answered"]
    assert events[-1].result.cited == ["SAMPLE-ACT#0"]  # type: ignore[union-attr]


async def test_ask_stream_without_llm_sends_passages_and_done(no_db: None) -> None:
    events = [e async for e in service.ask_stream("q?", None, FakeEmbedder(384), None, 2)]  # type: ignore[arg-type]
    assert [type(e).__name__ for e in events] == ["Retrieved", "Answered"]
    assert events[-1].result.mode == "retrieval_only"


# ---------- POST /ask/stream ----------


@pytest.fixture
async def client(no_db: None) -> AsyncIterator[AsyncClient]:
    async def no_session() -> AsyncIterator[None]:
        yield None

    app = create_app()
    app.dependency_overrides[get_reranker] = lambda: None
    app.dependency_overrides[get_ask_recorder] = lambda: None
    app.dependency_overrides[get_session] = no_session
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(384)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


async def stream_events(client: AsyncClient, question: str) -> list[tuple[str, dict[str, Any]]]:
    async with client.stream("POST", "/ask/stream", json={"question": question}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [line async for line in r.aiter_lines()]
    return list(parse_sse(iter(lines)))


async def test_stream_endpoint_sends_passages_tokens_done(client: AsyncClient) -> None:
    class Recorder:
        async def record(self, session: Any, question: str, result: Any, rid: str | None) -> int:
            assert result.streamed and result.answer == "".join(PIECES)
            return 7

    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_stream(PIECES))
    client.app.dependency_overrides[get_llm] = lambda: llm  # type: ignore[attr-defined]
    client.app.dependency_overrides[get_ask_recorder] = Recorder  # type: ignore[attr-defined]
    events = await stream_events(client, "When must I register?")
    names = [e for e, _ in events]
    assert names == ["passages"] + ["token"] * len(PIECES) + ["done"]
    assert [p["ref"] for p in events[0][1]["passages"]] == ["SAMPLE-ACT#0", "SAMPLE-RULES#2"]
    assert "".join(d["text"] for e, d in events if e == "token") == "".join(PIECES)
    done = events[-1][1]
    assert done["ask_id"] == 7 and done["cited"] == ["SAMPLE-ACT#0"]
    assert "first_token" in done["timings_ms"] and done["disclaimer"]


async def test_stream_endpoint_reports_llm_failure_as_an_event(client: AsyncClient) -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_stream([], status=503))
    client.app.dependency_overrides[get_llm] = lambda: llm  # type: ignore[attr-defined]
    events = await stream_events(client, "When must I register?")
    assert [e for e, _ in events] == ["passages", "error"]
    assert events[-1][1] == {"detail": "The language model is unavailable."}


async def test_stream_endpoint_validates_input(client: AsyncClient) -> None:
    client.app.dependency_overrides[get_llm] = lambda: None  # type: ignore[attr-defined]
    assert (await client.post("/ask/stream", json={"question": "?"})).status_code == 422


# ---------- client parser and usage report ----------


def test_parse_sse_handles_comments_and_multiple_events() -> None:
    lines = [": ping", "", "event: token", 'data: {"text": "a\\nb"}', "", "event: done", "data: {}"]
    assert list(parse_sse(iter(lines))) == [("token", {"text": "a\nb"}), ("done", {})]


async def test_report_counts_first_token_inside_generate(no_db: None) -> None:
    llm = OpenAICompatibleClient("http://llm/v1", "m", transport=fake_stream(PIECES))
    events = [e async for e in service.ask_stream("q?", None, FakeEmbedder(384), llm, 2)]  # type: ignore[arg-type]
    row = to_row("q?", events[-1].result, None)  # type: ignore[union-attr]
    row.timings_ms = {"embed": 10.0, "retrieve": 20.0, "first_token": 300.0, "generate": 4000.0}
    row.created_at = datetime.now(UTC)
    assert row.config["streamed"] is True

    class Session:
        async def scalars(self, stmt: Any) -> list[AskLog]:
            return [row]

    rep = await build_report(Session(), days=1)  # type: ignore[arg-type]
    assert rep.latency_ms["total"]["p50"] == 4030.0  # first_token is not added again
    assert rep.latency_ms["time_to_first_token"]["p50"] == 330.0
