"""The question-answering flow: embed -> retrieve -> prompt -> generate -> check."""

import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.embeddings import Embedder
from gst_copilot.rag.llm import LLMClient
from gst_copilot.rag.prompt import PROMPT_VERSION, build_messages, cited_refs, is_refusal
from gst_copilot.rag.retriever import RetrievedChunk, search

log = logging.getLogger("gst_copilot.rag")


@dataclass
class AskResult:
    mode: Literal["generated", "retrieval_only", "no_results"]
    answer: str | None
    retrieved: list[RetrievedChunk]
    cited: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    refused: bool = False
    timings_ms: dict[str, float] = field(default_factory=dict)
    prompt_version: str = PROMPT_VERSION
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


async def ask(
    question: str,
    session: AsyncSession,
    embedder: Embedder,
    llm: LLMClient | None,
    k: int,
) -> AskResult:
    t0 = time.perf_counter()
    qvec = embedder.embed_query(question)
    t1 = time.perf_counter()
    chunks = await search(session, qvec, k)
    t2 = time.perf_counter()
    timings = {"embed": _ms(t0, t1), "retrieve": _ms(t1, t2)}

    if not chunks:
        return AskResult(mode="no_results", answer=None, retrieved=[], timings_ms=timings)
    if llm is None:
        return AskResult(mode="retrieval_only", answer=None, retrieved=chunks, timings_ms=timings)

    completion = await llm.complete(build_messages(question, chunks))
    t3 = time.perf_counter()
    timings["generate"] = _ms(t2, t3)

    allowed = {c.ref for c in chunks}
    refs = cited_refs(completion.text)
    result = AskResult(
        mode="generated",
        answer=completion.text,
        retrieved=chunks,
        cited=[r for r in refs if r in allowed],
        # A tag the model invented is a red flag: it is citing something it wasn't shown.
        invalid_citations=[r for r in refs if r not in allowed],
        refused=is_refusal(completion.text),
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
