"""Store /ask calls and user feedback in ask_logs.

Logging must never break answering: if the write fails, the error is logged and
the user still gets the answer (with ask_id = null).
"""

import logging
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.db.models import AskLog
from gst_copilot.rag.service import AskResult

log = logging.getLogger("gst_copilot.observe")


class AskRecorder(Protocol):
    async def record(
        self, session: AsyncSession, question: str, result: AskResult, request_id: str | None
    ) -> int | None: ...


def to_row(question: str, result: AskResult, request_id: str | None) -> AskLog:
    s = get_settings()
    return AskLog(
        request_id=request_id,
        question=question,
        search_query=result.search_query,
        mode=result.mode,
        answer=result.answer,
        refused=result.refused,
        partial=result.partial,
        truncated=result.truncated,
        cited=list(result.cited),
        invalid_citations=list(result.invalid_citations),
        retrieved=[
            {
                "ref": c.ref,
                "section": c.section,
                "score": c.score,
                "vector_rank": c.vector_rank,
                "keyword_rank": c.keyword_rank,
                "rerank_score": c.rerank_score,
            }
            for c in result.retrieved
        ],
        context_refs=[c.ref for c in (result.context or result.retrieved)],
        timings_ms=dict(result.timings_ms),
        model=result.model,
        prompt_version=result.prompt_version,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        config={
            "chunker": s.chunker_version,
            "retrieval_mode": s.retrieval_mode,
            "reranker": s.reranker,
            "reranker_model": s.reranker_model,
            "query_expansion": s.query_expansion,
            "context_expansion": s.context_expansion,
            "embedding_model": s.embedding_model,
        },
    )


class DbAskRecorder:
    async def record(
        self, session: AsyncSession, question: str, result: AskResult, request_id: str | None
    ) -> int | None:
        try:
            row = to_row(question, result, request_id)
            session.add(row)
            await session.flush()  # assigns the id
            ask_id = row.id  # read it now: after commit the row is expired
            await session.commit()
            return ask_id
        except Exception:  # never fail the answer because logging failed
            log.exception("could not store ask log")
            try:
                await session.rollback()
            except Exception:
                log.exception("rollback after failed ask log also failed")
            return None


def get_ask_recorder() -> AskRecorder | None:
    return DbAskRecorder() if get_settings().ask_log_enabled else None


async def set_feedback(session: AsyncSession, ask_id: int, rating: int, note: str | None) -> bool:
    """Record 👍 (+1) or 👎 (-1) on a logged answer. False if the id does not exist."""
    row = await session.get(AskLog, ask_id)
    if row is None:
        return False
    row.feedback = rating
    row.feedback_note = note
    await session.commit()
    return True
