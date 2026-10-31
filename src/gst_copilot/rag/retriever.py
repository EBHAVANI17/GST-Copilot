"""Retrieval over chunks: vector search, keyword search, and hybrid (both, fused).

Vector search (pgvector): `<=>` is cosine distance, 0 = same direction. We report
similarity = 1 - distance, so higher is better. Good at meaning ("blocked credit"
finds "credit shall not be available").

Keyword search (Postgres full-text): matches the words themselves, stemmed
("credits" -> "credit"). Good at exact terms that embeddings blur: "180",
"section 16", "GSTR-3B".

Hybrid: run both, then merge the two ranked lists with Reciprocal Rank Fusion
(RRF): each chunk scores sum(1 / (rrf_k + rank)) over the lists it appears in.
RRF uses only ranks, so the two very different score scales never need tuning.
"""

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from sqlalchemy import Select, Text, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.db.models import Chunk, Document


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: str
    title: str
    source_url: str
    chunk_index: int
    text: str
    score: float  # cosine similarity to the question (shown to users, 1.0 = identical)
    section: str | None = None
    vector_rank: int | None = None  # 1-based rank in each list; None = not in that list
    keyword_rank: int | None = None
    rerank_score: float | None = None  # set when a reranker ordered the results

    @property
    def ref(self) -> str:
        """The citation tag the LLM must use, e.g. CGST-ACT-2017#12"""
        return f"{self.doc_id}#{self.chunk_index}"


def _base(query_vector: list[float], as_of: date | None = None) -> Select[Any]:
    distance = Chunk.embedding.cosine_distance(query_vector)
    stmt = select(
        Chunk.id,
        Document.doc_id,
        Document.title,
        Document.source_url,
        Chunk.chunk_index,
        Chunk.text,
        Chunk.section,
        distance.label("distance"),
    ).join(Document, Document.id == Chunk.document_id)
    if as_of is not None:
        stmt = stmt.where(
            (Document.effective_from.is_(None) | (Document.effective_from <= as_of))
            & (Document.effective_to.is_(None) | (Document.effective_to >= as_of))
        )
    return stmt


def _to_chunk(r: Any) -> RetrievedChunk:
    return RetrievedChunk(
        doc_id=r.doc_id,
        title=r.title,
        source_url=r.source_url,
        chunk_index=r.chunk_index,
        text=r.text,
        section=r.section,
        score=round(1.0 - float(r.distance), 4),
    )


async def vector_search(
    session: AsyncSession, query_vector: list[float], n: int, as_of: date | None = None
) -> dict[int, RetrievedChunk]:
    stmt = _base(query_vector, as_of=as_of).order_by("distance").limit(n)
    rows = (await session.execute(stmt)).all()
    return {r.id: _to_chunk(r) for r in rows}


async def keyword_search(
    session: AsyncSession,
    query_vector: list[float],
    query_text: str,
    n: int,
    as_of: date | None = None,
) -> dict[int, RetrievedChunk]:
    # plainto_tsquery ANDs every word, which almost never matches a whole question.
    # Turning "&" into "|" means "any of these words"; ts_rank_cd then prefers chunks
    # that contain more of them, closer together.
    words = func.plainto_tsquery("english", query_text).cast(Text)
    # Cast directly (not to_tsquery again), so the already-stemmed words aren't re-stemmed.
    tsq = func.replace(words, "&", "|").cast(TSQUERY)
    rank = func.ts_rank_cd(Chunk.tsv, tsq)
    stmt = (
        _base(query_vector, as_of=as_of)
        .add_columns(rank.label("kw"))
        .where(Chunk.tsv.op("@@")(tsq))
        .order_by(rank.desc())
        .limit(n)
    )
    rows = (await session.execute(stmt)).all()
    return {r.id: _to_chunk(r) for r in rows}


def rrf_fuse(
    vector: dict[int, RetrievedChunk], keyword: dict[int, RetrievedChunk], k: int, rrf_k: int
) -> list[RetrievedChunk]:
    """Merge two ranked lists (dicts keep insertion order = rank order) by RRF."""
    v_rank = {cid: i for i, cid in enumerate(vector, start=1)}
    kw_rank = {cid: i for i, cid in enumerate(keyword, start=1)}
    scores: dict[int, float] = {}
    for ranks in (v_rank, kw_rank):
        for cid, rank in ranks.items():
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
    best = sorted(scores, key=lambda cid: (-scores[cid], v_rank.get(cid, 10**9)))[:k]
    return [
        replace(
            vector.get(cid) or keyword[cid],
            vector_rank=v_rank.get(cid),
            keyword_rank=kw_rank.get(cid),
        )
        for cid in best
    ]


async def search(
    session: AsyncSession,
    query_vector: list[float],
    k: int,
    query_text: str | None = None,
    as_of: date | None = None,
) -> list[RetrievedChunk]:
    """Top-k chunks. Hybrid when enabled and the question text is given, else vector only."""
    s = get_settings()
    if s.retrieval_mode == "vector" or not query_text:
        hits = await vector_search(session, query_vector, k, as_of=as_of)
        return [replace(c, vector_rank=i) for i, c in enumerate(hits.values(), start=1)]
    n = max(s.retrieval_candidates, k)
    vector = await vector_search(session, query_vector, n, as_of=as_of)
    keyword = await keyword_search(session, query_vector, query_text, n, as_of=as_of)
    return rrf_fuse(vector, keyword, k, s.rrf_k)


async def candidate_pool(
    session: AsyncSession,
    query_vector: list[float],
    query_text: str,
    n: int,
    as_of: date | None = None,
) -> list[RetrievedChunk]:
    """Wide candidate list for a reranker: top n from vector search, plus top n from
    keyword search when RETRIEVAL_MODE=hybrid (duplicates merged, RRF order)."""
    vector = await vector_search(session, query_vector, n, as_of=as_of)
    if get_settings().retrieval_mode == "vector":
        return [replace(c, vector_rank=i) for i, c in enumerate(vector.values(), start=1)]
    keyword = await keyword_search(session, query_vector, query_text, n, as_of=as_of)
    return rrf_fuse(vector, keyword, k=2 * n, rrf_k=get_settings().rrf_k)
