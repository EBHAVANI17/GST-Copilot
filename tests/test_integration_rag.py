"""Integration tests: real PostgreSQL + pgvector, fake embeddings.

Run with:  EMBEDDING_PROVIDER=fake pytest -m integration
Needs the database up and migrated (docker compose up db, then alembic upgrade head).
They reset the documents and chunks tables, so never point them at real data.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from gst_copilot.config import get_settings
from gst_copilot.db.models import Chunk
from gst_copilot.embeddings import FakeEmbedder
from gst_copilot.ingest.pipeline import ingest_manifest
from gst_copilot.rag.retriever import search

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parent / "fixtures" / "sample_corpus"
EMB = FakeEmbedder(384)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE documents RESTART IDENTITY CASCADE"))
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
    await engine.dispose()


async def test_ingest_is_idempotent(session: AsyncSession) -> None:
    first = await ingest_manifest(session, EMB, FIXTURES / "manifest.csv")
    assert sorted(first.added) == ["SAMPLE-ACT", "SAMPLE-RULES", "SAMPLE-SCHEDULE"]
    assert first.chunks_written >= 4  # the schedule is long enough to need several chunks

    second = await ingest_manifest(session, EMB, FIXTURES / "manifest.csv")
    assert second.added == [] and second.updated == [] and second.chunks_written == 0
    assert len(second.unchanged) == 3
    total = await session.scalar(select(func.count()).select_from(Chunk))
    assert total == first.chunks_written


async def test_changed_and_removed_documents(session: AsyncSession, tmp_path: Path) -> None:
    for name in ("registration.txt", "credit.txt"):
        (tmp_path / name).write_text((FIXTURES / name).read_text())
    rows = (FIXTURES / "manifest.csv").read_text().splitlines()[:3]  # header + 2 docs
    (tmp_path / "manifest.csv").write_text("\n".join(rows) + "\n")
    await ingest_manifest(session, EMB, tmp_path / "manifest.csv")

    (tmp_path / "credit.txt").write_text("Amended rule text about credit.")
    (tmp_path / "manifest.csv").write_text("\n".join([rows[0], rows[2]]) + "\n")  # drop the Act
    report = await ingest_manifest(session, EMB, tmp_path / "manifest.csv")
    assert report.updated == ["SAMPLE-RULES"]
    assert report.removed == ["SAMPLE-ACT"]


async def test_vector_search_finds_the_right_document(session: AsyncSession) -> None:
    await ingest_manifest(session, EMB, FIXTURES / "manifest.csv")
    cases = {
        "within how many days must a supplier apply for registration": "SAMPLE-ACT",
        "input credit monthly credit statement invoice": "SAMPLE-RULES",
        "levy rate category blue widgets schedule": "SAMPLE-SCHEDULE",
    }
    for question, expected in cases.items():
        hits = await search(session, EMB.embed_query(question), k=3)
        assert hits[0].doc_id == expected, f"{question!r} -> {[h.doc_id for h in hits]}"
        assert hits[0].score >= hits[-1].score  # sorted best first
