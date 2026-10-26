"""The question-answering flow: embed -> retrieve -> prompt -> generate -> check."""

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.embeddings import Embedder
from gst_copilot.rag.expand import expand
from gst_copilot.rag.glossary import expand_query
from gst_copilot.rag.llm import LLMClient
from gst_copilot.rag.prompt import build_messages, cited_refs, is_partial, is_refusal
from gst_copilot.rag.rerank import Reranker, rerank
from gst_copilot.rag.retriever import RetrievedChunk, candidate_pool, search

log = logging.getLogger("gst_copilot.rag")


@dataclass
class AskResult:
    mode: Literal["generated", "retrieval_only", "no_results"]
    answer: str | None
    retrieved: list[RetrievedChunk]  # top-k as ranked (retrieval metrics use this)
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


async def ask(
    question: str,
    session: AsyncSession,
    embedder: Embedder,
    llm: LLMClient | None,
    k: int,
    reranker: Reranker | None = None,
) -> AskResult:
    t0 = time.perf_counter()
    # Search with the law's wording added; the LLM still gets the original question.
    query = expand_query(question) if get_settings().query_expansion == "glossary" else question
    qvec = embedder.embed_query(query)
    t1 = time.perf_counter()
    if reranker is None:
        chunks = await search(session, qvec, k, query_text=query)
        t2 = time.perf_counter()
        timings = {"embed": _ms(t0, t1), "retrieve": _ms(t1, t2)}
    else:
        n = max(get_settings().rerank_candidates, k)
        pool = await candidate_pool(session, qvec, query, n)
        tr = time.perf_counter()
        chunks = rerank(reranker, query, pool, k)
        t2 = time.perf_counter()
        timings = {"embed": _ms(t0, t1), "retrieve": _ms(t1, tr), "rerank": _ms(tr, t2)}

    if not chunks:
        return AskResult(mode="no_results", answer=None, retrieved=[], timings_ms=timings)

    settings = get_settings()
    context = chunks
    if settings.context_expansion == "section":
        context = await expand(session, chunks, qvec, settings.context_max_chars)
        t2b = time.perf_counter()
        timings["expand"] = _ms(t2, t2b)
        t2 = t2b
    if llm is None:
        return AskResult(
            mode="retrieval_only",
            answer=None,
            retrieved=chunks,
            context=context,
            timings_ms=timings,
        )

    version = settings.prompt_version
    completion = await llm.complete(build_messages(question, context, version))
    t3 = time.perf_counter()
    timings["generate"] = _ms(t2, t3)

    allowed = {c.ref for c in context}
    refs = cited_refs(completion.text)
    result = AskResult(
        mode="generated",
        answer=completion.text,
        retrieved=chunks,
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
    )
    log.info(
        "question answered",
        extra={
            "fields": {
                "mode": result.mode,
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


def _ms(a: float, b: float) -> float:
    return round((b - a) * 1000, 1)
