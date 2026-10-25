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


async def test_changing_the_chunker_rechunks_and_stores_sections(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    act = Path(__file__).parent / "fixtures" / "widget_act.txt"
    (tmp_path / "act.txt").write_text(act.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "manifest.csv").write_text(
        "doc_id,doc_type,title,source_url,issued_on,effective_from,effective_to,file\n"
        "WIDGET-ACT,act,Widget Levy Act (synthetic),https://example.invalid/w,"
        "2020-01-01,2020-04-01,,act.txt\n"
    )

    monkeypatch.setenv("CHUNKING_STRATEGY", "fixed")
    get_settings.cache_clear()
    first = await ingest_manifest(session, EMB, tmp_path / "manifest.csv")
    assert first.added == ["WIDGET-ACT"]
    assert set(await session.scalars(select(Chunk.section))) == {None}

    monkeypatch.setenv("CHUNKING_STRATEGY", "section")
    get_settings.cache_clear()
    second = await ingest_manifest(session, EMB, tmp_path / "manifest.csv")
    assert second.updated == ["WIDGET-ACT"], "same file, new chunker: must re-chunk"
    sections = set(await session.scalars(select(Chunk.section)))
    assert {"16", "17", "17A"} <= sections

    third = await ingest_manifest(session, EMB, tmp_path / "manifest.csv")
    assert third.unchanged == ["WIDGET-ACT"]

    hits = await search(session, EMB.embed_query("claimed depreciation on the levy component"), 3)
    assert hits[0].section == "16"
    assert hits[0].text.startswith("Section 16. Eligibility and conditions")
    get_settings.cache_clear()


async def test_hybrid_search_matches_digits_against_numbers_in_words(
    session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    get_settings.cache_clear()
    (tmp_path / "act.txt").write_text(
        "SYNTHETIC TEST DOCUMENT.\n\n"
        "5. Registration.—(1) Apply for registration within thirty days.\n\n"
        "6. Payment to supplier.—(1) Where a buyer fails to pay the supplier within a period "
        "of one hundred and eighty days, the credit shall be reversed.\n\n"
        "7. Records.—(1) Keep accounts for seventy-two months.\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.csv").write_text(
        "doc_id,doc_type,title,source_url,issued_on,effective_from,effective_to,file\n"
        "NUM-ACT,act,Numbers Act (synthetic),https://example.invalid/n,2020-01-01,2020-04-01,,"
        "act.txt\n"
    )
    await ingest_manifest(session, EMB, tmp_path / "manifest.csv")

    question = "What if I do not pay within 180 days?"
    hits = await search(session, EMB.embed_query(question), k=3, query_text=question)
    assert hits[0].section == "6"
    assert "one hundred and eighty (180) days" in hits[0].text
    assert hits[0].keyword_rank == 1, "keyword search must match the digits"

    vector_only = await search(session, EMB.embed_query(question), k=3)
    assert all(h.keyword_rank is None for h in vector_only)
    get_settings.cache_clear()


async def test_reranker_over_a_hybrid_candidate_pool(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gst_copilot.rag.rerank import FakeReranker
    from gst_copilot.rag.service import ask

    await ingest_manifest(session, EMB, FIXTURES / "manifest.csv")
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("RERANK_CANDIDATES", "5")
    get_settings.cache_clear()
    result = await ask(
        "When can a buyer take input credit on widget purchases?",
        session,
        EMB,
        None,
        2,
        FakeReranker(),
    )
    assert result.mode == "retrieval_only"
    assert result.retrieved[0].doc_id == "SAMPLE-RULES"
    assert result.retrieved[0].rerank_score is not None
    assert set(result.timings_ms) == {"embed", "retrieve", "rerank"}
    get_settings.cache_clear()
