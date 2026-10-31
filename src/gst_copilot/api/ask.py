"""POST /ask: answer a GST question from the indexed documents, with citations.

POST /ask/stream: the same answer as server-sent events, so the client can show the
passages at once and the answer word by word while the model writes it.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.db.session import get_session
from gst_copilot.embeddings import Embedder, get_embedder
from gst_copilot.logging import request_id_var
from gst_copilot.observe.store import AskRecorder, get_ask_recorder
from gst_copilot.rag.llm import LLMClient, LLMError, get_llm
from gst_copilot.rag.rerank import Reranker, get_reranker
from gst_copilot.rag.service import AskResult, Retrieved, Token, ask, ask_stream

log = logging.getLogger("gst_copilot.api")
router = APIRouter(tags=["ask"])
LLM_UNAVAILABLE = "The language model is unavailable."


class AskRequest(BaseModel):
    question: str = Field(description="3 to ASK_MAX_QUESTION_CHARS (1000) characters")
    top_k: int | None = Field(default=None, ge=1, le=20)
    as_of: date | None = Field(
        default=None,
        description="Filter retrieval to provisions in force on this date (YYYY-MM-DD)",
    )

    @field_validator("question")
    @classmethod
    def _length(cls, value: str) -> str:
        # Trim first, so "   " is not a question; the limit is a setting (ADR 0025).
        value = value.strip()
        limit = get_settings().ask_max_question_chars
        if len(value) < 3:
            raise ValueError("question must have at least 3 characters")
        if len(value) > limit:
            raise ValueError(f"question must have at most {limit} characters")
        return value


class Passage(BaseModel):
    ref: str
    doc_id: str
    title: str
    source_url: str
    section: str | None
    score: float
    # Rank in vector / keyword search (1 = best); null = not found by that search.
    vector_rank: int | None
    keyword_rank: int | None
    rerank_score: float | None
    cited: bool  # in /ask/stream's "passages" event always false: see "done".cited
    text: str


class AskResponse(BaseModel):
    ask_id: int | None = None  # send it to POST /feedback; null if logging is off or failed
    mode: Literal["generated", "retrieval_only", "no_results"]
    answer: str | None
    refused: bool
    partial: bool
    truncated: bool
    passages: list[Passage]
    invalid_citations: list[str]
    prompt_version: str | None
    model: str | None
    timings_ms: dict[str, float]
    disclaimer: str = "Information, not tax advice."
    as_of: date | None = None
    sub_queries: list[str] = Field(default_factory=list)


@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient | None, Depends(get_llm)],
    reranker: Annotated[Reranker | None, Depends(get_reranker)],
    recorder: Annotated[AskRecorder | None, Depends(get_ask_recorder)],
) -> AskResponse:
    k = body.top_k or get_settings().retrieval_top_k
    try:
        result = await ask(body.question, session, embedder, llm, k, reranker, as_of=body.as_of)
    except LLMError as exc:
        # Don't leak provider details to the caller; they are in the logs.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, LLM_UNAVAILABLE) from exc
    ask_id = (
        await recorder.record(session, body.question, result, request_id_var.get())
        if recorder is not None
        else None
    )
    return AskResponse(
        ask_id=ask_id,
        mode=result.mode,
        answer=result.answer,
        refused=result.refused,
        partial=result.partial,
        truncated=result.truncated,
        passages=_passages(result),
        invalid_citations=result.invalid_citations,
        prompt_version=result.prompt_version,
        model=result.model,
        timings_ms=result.timings_ms,
        disclaimer=_build_disclaimer(result),
        as_of=result.as_of,
        sub_queries=result.sub_queries,
    )


def _build_disclaimer(result: AskResult) -> str:
    base = "Information, not tax advice."
    chunks = result.context or result.retrieved
    if not chunks:
        return base
    titles: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        if c.title and c.title not in seen:
            seen.add(c.title)
            titles.append(c.title)
    if not titles:
        return base
    return f"{base} Law versions used: {'; '.join(titles)}. Law may have changed after these dates."


def _passages(result: AskResult) -> list[Passage]:
    cited = set(result.cited)
    return [
        Passage(
            ref=c.ref,
            doc_id=c.doc_id,
            title=c.title,
            source_url=c.source_url,
            section=c.section,
            score=c.score,
            vector_rank=c.vector_rank,
            keyword_rank=c.keyword_rank,
            rerank_score=c.rerank_score,
            cited=c.ref in cited,
            text=c.text,
        )
        for c in (result.context or result.retrieved)
    ]


class StreamDone(BaseModel):
    """The last event of /ask/stream: everything /ask returns except the passages."""

    ask_id: int | None = None
    mode: Literal["generated", "retrieval_only", "no_results"]
    answer: str | None
    refused: bool
    partial: bool
    truncated: bool
    cited: list[str]
    invalid_citations: list[str]
    prompt_version: str | None
    model: str | None
    timings_ms: dict[str, float]
    disclaimer: str = "Information, not tax advice."
    as_of: date | None = None
    sub_queries: list[str] = Field(default_factory=list)


def sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    """One server-sent event. JSON has no raw newlines, so "data:" is one line."""
    payload = (
        data.model_dump_json()
        if isinstance(data, BaseModel)
        else json.dumps(data, ensure_ascii=False)
    )
    return f"event: {event}\ndata: {payload}\n\n"


STREAM_DOC = """Server-sent events (text/event-stream), in this order:

- `passages`: `{"mode", "search_query", "passages": [...]}` before generation starts
- `token`: `{"text": "..."}` many times, the answer as the model writes it
- `done`: `{"ask_id", "answer", "refused", "cited", "timings_ms", ...}` (see StreamDone)
- `error`: `{"detail": "..."}` instead of `done` if the language model fails

The HTTP status is 200 once streaming starts, so errors arrive as an `error` event."""


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    description=STREAM_DOC,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Event stream"}},
)
async def ask_stream_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient | None, Depends(get_llm)],
    reranker: Annotated[Reranker | None, Depends(get_reranker)],
    recorder: Annotated[AskRecorder | None, Depends(get_ask_recorder)],
) -> StreamingResponse:
    k = body.top_k or get_settings().retrieval_top_k
    # The body is sent after the request middleware has finished, so keep the ID now.
    request_id = request_id_var.get()

    async def events() -> AsyncIterator[str]:
        token = request_id_var.set(request_id)
        try:
            async for event in ask_stream(
                body.question, session, embedder, llm, k, reranker, as_of=body.as_of
            ):
                if isinstance(event, Token):
                    yield sse("token", {"text": event.text})
                elif isinstance(event, Retrieved):
                    r = event.result
                    yield sse(
                        "passages",
                        {
                            "mode": r.mode,
                            "search_query": r.search_query,
                            "sub_queries": r.sub_queries,
                            "passages": [p.model_dump() for p in _passages(r)],
                        },
                    )
                else:
                    r = event.result
                    ask_id = (
                        await recorder.record(session, body.question, r, request_id)
                        if recorder is not None
                        else None
                    )
                    yield sse(
                        "done",
                        StreamDone(
                            ask_id=ask_id,
                            mode=r.mode,
                            answer=r.answer,
                            refused=r.refused,
                            partial=r.partial,
                            truncated=r.truncated,
                            cited=r.cited,
                            invalid_citations=r.invalid_citations,
                            prompt_version=r.prompt_version,
                            model=r.model,
                            timings_ms=r.timings_ms,
                            disclaimer=_build_disclaimer(r),
                            as_of=r.as_of,
                            sub_queries=r.sub_queries,
                        ),
                    )
        except LLMError as exc:
            log.warning("stream failed", extra={"fields": {"error": str(exc)}})
            yield sse("error", {"detail": LLM_UNAVAILABLE})
        finally:
            request_id_var.reset(token)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # no-cache: never store; X-Accel-Buffering: tell nginx not to buffer the stream.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
