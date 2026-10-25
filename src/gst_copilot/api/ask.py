"""POST /ask: answer a GST question from the indexed documents, with citations."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.db.session import get_session
from gst_copilot.embeddings import Embedder, get_embedder
from gst_copilot.rag.llm import LLMClient, LLMError, get_llm
from gst_copilot.rag.rerank import Reranker, get_reranker
from gst_copilot.rag.service import ask

router = APIRouter(tags=["ask"])


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)


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
    cited: bool
    text: str


class AskResponse(BaseModel):
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


@router.post("/ask", response_model=AskResponse)
async def ask_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    llm: Annotated[LLMClient | None, Depends(get_llm)],
    reranker: Annotated[Reranker | None, Depends(get_reranker)],
) -> AskResponse:
    k = body.top_k or get_settings().retrieval_top_k
    try:
        result = await ask(body.question, session, embedder, llm, k, reranker)
    except LLMError as exc:
        # Don't leak provider details to the caller; they are in the logs.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The language model is unavailable."
        ) from exc
    cited = set(result.cited)
    return AskResponse(
        mode=result.mode,
        answer=result.answer,
        refused=result.refused,
        partial=result.partial,
        truncated=result.truncated,
        passages=[
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
            for c in result.retrieved
        ],
        invalid_citations=result.invalid_citations,
        prompt_version=result.prompt_version,
        model=result.model,
        timings_ms=result.timings_ms,
    )
