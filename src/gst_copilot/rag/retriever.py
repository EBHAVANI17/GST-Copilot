"""Vector search over chunks with pgvector.

`<=>` is pgvector's cosine distance operator: 0 = same direction, 2 = opposite.
We report similarity = 1 - distance, so higher is better (1.0 = identical).
The HNSW index from migration 0002 makes ORDER BY ... LIMIT k fast.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.db.models import Chunk, Document


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: str
    title: str
    source_url: str
    chunk_index: int
    text: str
    score: float
    section: str | None = None

    @property
    def ref(self) -> str:
        """The citation tag the LLM must use, e.g. CGST-ACT-2017#12"""
        return f"{self.doc_id}#{self.chunk_index}"


async def search(session: AsyncSession, query_vector: list[float], k: int) -> list[RetrievedChunk]:
    distance = Chunk.embedding.cosine_distance(query_vector)
    stmt = (
        select(
            Document.doc_id,
            Document.title,
            Document.source_url,
            Chunk.chunk_index,
            Chunk.text,
            Chunk.section,
            distance.label("distance"),
        )
        .join(Document, Document.id == Chunk.document_id)
        .order_by(distance)
        .limit(k)
    )
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            doc_id=r.doc_id,
            title=r.title,
            source_url=r.source_url,
            chunk_index=r.chunk_index,
            text=r.text,
            score=round(1.0 - float(r.distance), 4),
            section=r.section,
        )
        for r in rows
    ]
