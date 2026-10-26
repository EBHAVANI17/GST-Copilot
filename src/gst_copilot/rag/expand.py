"""Section expansion ("small-to-big" retrieval).

Search ranks small pieces, which is precise. But a long section (s.16 has six
pieces) is then shown to the LLM as scattered fragments: for "conditions for
taking ITC", retrieval returned s.16 pieces 77, 80 and 81 and missed 78-79, the
pieces that list the conditions. The section was right; the pieces were wrong.

So: use the ranked pieces to choose sections, then give the LLM each chosen
section whole and in order, best section first, within a character budget (the
local LLM's context window is only 4,096 tokens, and Ollama silently drops the
start of a prompt that is too long, which is where our rules are).

If a whole section does not fit, we keep its ranked pieces plus their direct
neighbours, so the text around each hit is still there.
"""

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.db.models import Chunk, Document
from gst_copilot.rag.retriever import RetrievedChunk

SectionKey = tuple[str, str]  # (doc_id, section)


def _key(c: RetrievedChunk) -> SectionKey | None:
    return (c.doc_id, c.section) if c.section is not None else None


def expand_sections(
    ranked: list[RetrievedChunk],
    sections: dict[SectionKey, list[RetrievedChunk]],
    max_chars: int,
) -> list[RetrievedChunk]:
    """Pure function: ranked pieces + all pieces of their sections -> LLM context."""
    by_ref = {c.ref: c for c in ranked}  # keep rerank scores and ranks for ranked pieces
    out: list[RetrievedChunk] = []
    seen: set[str] = set()
    used = 0

    def add(c: RetrievedChunk) -> bool:
        nonlocal used
        if c.ref in seen:
            return True
        if out and used + len(c.text) > max_chars:  # always allow at least one piece
            return False
        out.append(by_ref.get(c.ref, c))
        seen.add(c.ref)
        used += len(c.text)
        return True

    done: set[SectionKey] = set()
    for hit in ranked:
        key = _key(hit)
        if key is None or key not in sections:
            add(hit)
            continue
        if key in done:
            continue
        done.add(key)
        pieces = sections[key]
        if used + sum(len(p.text) for p in pieces if p.ref not in seen) <= max_chars:
            for p in pieces:
                add(p)
            continue
        # Too big: the ranked pieces of this section plus one neighbour on each side.
        wanted: set[int] = set()
        indexes = [p.chunk_index for p in pieces]
        for r in ranked:
            if _key(r) == key and r.chunk_index in indexes:
                i = indexes.index(r.chunk_index)
                wanted.update(j for j in (i - 1, i, i + 1) if 0 <= j < len(pieces))
        for j in sorted(wanted):
            add(pieces[j])
    return out


async def fetch_sections(
    session: AsyncSession, keys: list[SectionKey], query_vector: list[float]
) -> dict[SectionKey, list[RetrievedChunk]]:
    """All pieces of the given sections, in document order."""
    if not keys:
        return {}
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
        .where(tuple_(Document.doc_id, Chunk.section).in_(keys))
        .order_by(Document.doc_id, Chunk.chunk_index)
    )
    out: dict[SectionKey, list[RetrievedChunk]] = {}
    for r in (await session.execute(stmt)).all():
        chunk = RetrievedChunk(
            doc_id=r.doc_id,
            title=r.title,
            source_url=r.source_url,
            chunk_index=r.chunk_index,
            text=r.text,
            section=r.section,
            score=round(1.0 - float(r.distance), 4),
        )
        out.setdefault((r.doc_id, r.section), []).append(chunk)
    return out


async def expand(
    session: AsyncSession,
    ranked: list[RetrievedChunk],
    query_vector: list[float],
    max_chars: int,
) -> list[RetrievedChunk]:
    keys = list(dict.fromkeys(k for c in ranked if (k := _key(c)) is not None))
    return expand_sections(ranked, await fetch_sections(session, keys, query_vector), max_chars)
