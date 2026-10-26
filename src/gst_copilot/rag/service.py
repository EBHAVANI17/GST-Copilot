"""The question-answering flow: embed -> retrieve -> prompt -> generate -> check.

ask() returns the whole result at once; ask_stream() yields the same result as
events, so the answer can be shown while the model is still writing it.
"""

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.embeddings import Embedder
from gst_copilot.rag.expand import expand
from gst_copilot.rag.glossary import expand_query
from gst_copilot.rag.llm import Completion, LLMClient, LLMError, StreamingLLMClient
from gst_copilot.rag.prompt import build_messages, cited_refs, is_partial, is_refusal
from gst_copilot.rag.rerank import Reranker, rerank
from gst_copilot.rag.retriever import RetrievedChunk, candidate_pool, search

log = logging.getLogger("gst_copilot.rag")


@dataclass
class AskResult:
    mode: Literal["generated", "retrieval_only", "no_results"]
    answer: str | None
    retrieved: list[RetrievedChunk]  # top-k as ranked (retrieval metrics use this)
    search_query: str | None = None  # the question as searched (after glossary expansion)
    context: list[RetrievedChunk] = field(default_factory=list)  # what the LLM was shown
    cited: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    refused: bool = False
    partial: bool = False  # answered part, said the rest is not covered
    truncated: bool = False  # the answer hit llm_max_tokens and was cut off
    timings_ms: dict[str, float] = field(default_factory=dict)
    prompt_version: str | None = None  # None when no LLM was called
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    streamed: bool = False  # answered through POST /ask/stream


async def _retrieve(
    question: str,
    session: AsyncSession,
    embedder: Embedder,
    k: int,
    reranker: Reranker | None,
) -> tuple[str, list[RetrievedChunk], list[RetrievedChunk], dict[str, float]]:
    """Embed, search, rerank, expand: (search query, top-k, LLM context, timings)."""
    t0 = time.perf_counter()
    settings = get_settings()
    # Search with the law's wording added; the LLM still gets the original question.
    query = expand_query(question) if settings.query_expansion == "glossary" else question
    qvec = embedder.embed_query(query)
    t1 = time.perf_counter()
    if reranker is None:
        chunks = await search(session, qvec, k, query_text=query)
        t2 = time.perf_counter()
        timings = {"embed": _ms(t0, t1), "retrieve": _ms(t1, t2)}
    else:
        n = max(settings.rerank_candidates, k)
        pool = await candidate_pool(session, qvec, query, n)
        tr = time.perf_counter()
        chunks = rerank(reranker, query, pool, k)
        t2 = time.perf_counter()
        timings = {"embed": _ms(t0, t1), "retrieve": _ms(t1, tr), "rerank": _ms(tr, t2)}

    context = chunks
    if chunks and settings.context_expansion == "section":
        context = await expand(session, chunks, qvec, settings.context_max_chars)
        timings["expand"] = _ms(t2, time.perf_counter())
    return query, chunks, context, timings


def _without_llm(
    query: str,
    chunks: list[RetrievedChunk],
    context: list[RetrievedChunk],
    timings: dict[str, float],
) -> AskResult:
    if not chunks:
        return AskResult(
            mode="no_results", answer=None, retrieved=[], search_query=query, timings_ms=timings
        )
    return AskResult(
        mode="retrieval_only",
        answer=None,
        retrieved=chunks,
        search_query=query,
        context=context,
        timings_ms=timings,
    )


def _answered(
    query: str,
    chunks: list[RetrievedChunk],
    context: list[RetrievedChunk],
    completion: Completion,
    version: str,
    timings: dict[str, float],
    streamed: bool = False,
) -> AskResult:
    allowed = {c.ref for c in context}
    refs = cited_refs(completion.text)
    result = AskResult(
        mode="generated",
        answer=completion.text,
        retrieved=chunks,
        search_query=query,
        context=context,
        cited=[r for r in refs if r in allowed],
        # A tag the model invented is a red flag: it is citing something it wasn't shown.
        invalid_citations=[r for r in refs if r not in allowed],
        refused=is_refusal(completion.text),
        partial=is_partial(completion.text),
        truncated=completion.truncated,
        prompt_version=version,
        timings_ms=timings,
        model=completion.model,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        streamed=streamed,
    )
    log.info(
        "question answered",
        extra={
            "fields": {
                "mode": result.mode,
                "streamed": streamed,
                "refused": result.refused,
                "partial": result.partial,
                "truncated": result.truncated,
                "prompt_version": result.prompt_version,
                "cited": len(result.cited),
                "invalid_citations": len(result.invalid_citations),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                **{f"ms_{k}": v for k, v in timings.items()},
            }
        },
    )
    return result


async def ask(
    question: str,
    session: AsyncSession,
    embedder: Embedder,
    llm: LLMClient | None,
    k: int,
    reranker: Reranker | None = None,
) -> AskResult:
    query, chunks, context, timings = await _retrieve(question, session, embedder, k, reranker)
    if not chunks or llm is None:
        return _without_llm(query, chunks, context, timings)
    version = get_settings().prompt_version
    t = time.perf_counter()
    completion = await llm.complete(build_messages(question, context, version))
    timings["generate"] = _ms(t, time.perf_counter())
    return _answered(query, chunks, context, completion, version, timings)


# ---------- streaming: the same flow, the answer sent piece by piece ----------


@dataclass(frozen=True)
class Retrieved:
    """First event: the passages, before the LLM starts (answer is still None)."""

    result: AskResult


@dataclass(frozen=True)
class Token:
    text: str


@dataclass(frozen=True)
class Answered:
    """Last event: the finished result, with citation checks, flags and timings."""

    result: AskResult


StreamEvent = Retrieved | Token | Answered


async def ask_stream(
    question: str,
    session: AsyncSession,
    embedder: Embedder,
    llm: LLMClient | None,
    k: int,
    reranker: Reranker | None = None,
) -> AsyncIterator[StreamEvent]:
    """Retrieved, then Token* as the model writes, then Answered.

    timings_ms gets "first_token": ms from the start of generation to the first
    piece of text. It is part of "generate", not an extra stage. Citation and
    refusal checks need the whole answer, so they arrive only with Answered.
    """
    query, chunks, context, timings = await _retrieve(question, session, embedder, k, reranker)
    if not chunks or llm is None:
        result = _without_llm(query, chunks, context, timings)
        yield Retrieved(result)
        yield Answered(result)
        return

    yield Retrieved(
        AskResult(
            mode="generated",
            answer=None,
            retrieved=chunks,
            search_query=query,
            context=context,
            timings_ms=dict(timings),
        )
    )
    version = get_settings().prompt_version
    messages = build_messages(question, context, version)
    t = time.perf_counter()
    completion: Completion | None = None
    if isinstance(llm, StreamingLLMClient):
        async for piece in llm.stream(messages):
            if isinstance(piece, Completion):
                completion = piece
                continue
            timings.setdefault("first_token", _ms(t, time.perf_counter()))
            yield Token(piece)
        if completion is None:
            raise LLMError("LLM stream ended without a final result")
    else:  # a client that cannot stream: one piece with the whole answer
        completion = await llm.complete(messages)
        timings["first_token"] = _ms(t, time.perf_counter())
        if completion.text:
            yield Token(completion.text)
    timings["generate"] = _ms(t, time.perf_counter())
    yield Answered(_answered(query, chunks, context, completion, version, timings, streamed=True))


def _ms(a: float, b: float) -> float:
    return round((b - a) * 1000, 1)
