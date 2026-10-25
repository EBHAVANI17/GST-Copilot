"""Ingestion: manifest -> text -> chunks -> embeddings -> database.

Idempotent: running it twice does no extra work. Each document's file hash is
stored; unchanged documents are skipped, changed ones are re-chunked and
re-embedded, and documents removed from the manifest are deleted.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from gst_copilot.config import get_settings
from gst_copilot.db.models import Chunk, Document
from gst_copilot.embeddings import Embedder
from gst_copilot.ingest.chunking import chunk_text
from gst_copilot.ingest.extract import extract_text
from gst_copilot.ingest.manifest import ManifestEntry, load_manifest

log = logging.getLogger("gst_copilot.ingest")


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    chunks_written: int = 0
    seconds: float = 0.0


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


async def ingest_manifest(
    session: AsyncSession, embedder: Embedder, manifest_path: Path
) -> IngestReport:
    start = time.perf_counter()
    settings = get_settings()
    entries = load_manifest(manifest_path)
    report = IngestReport()

    existing = {d.doc_id: d for d in (await session.scalars(select(Document))).all()}

    for entry in entries:
        sha = file_sha256(entry.path)
        doc = existing.get(entry.doc_id)
        if doc is not None and doc.sha256 == sha:
            _copy_metadata(doc, entry)  # metadata edits in the CSV still apply
            report.unchanged.append(entry.doc_id)
            continue

        text = extract_text(entry.path)
        pieces = chunk_text(text, settings.chunk_size_chars, settings.chunk_overlap_chars)
        vectors = embedder.embed_documents(pieces)

        if doc is None:
            doc = Document(doc_id=entry.doc_id, sha256=sha)
            _copy_metadata(doc, entry)
            session.add(doc)
            await session.flush()  # assigns doc.id
            report.added.append(entry.doc_id)
        else:
            doc.sha256 = sha
            _copy_metadata(doc, entry)
            await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            report.updated.append(entry.doc_id)

        session.add_all(
            Chunk(document_id=doc.id, chunk_index=i, text=t, embedding=v)
            for i, (t, v) in enumerate(zip(pieces, vectors, strict=True))
        )
        report.chunks_written += len(pieces)
        log.info(
            "document ingested",
            extra={"fields": {"doc_id": entry.doc_id, "chunks": len(pieces)}},
        )

    manifest_ids = {e.doc_id for e in entries}
    for doc_id, doc in existing.items():
        if doc_id not in manifest_ids:
            await session.delete(doc)  # chunks go too (ON DELETE CASCADE)
            report.removed.append(doc_id)

    # One transaction: either the whole run is saved, or none of it.
    await session.commit()
    report.seconds = round(time.perf_counter() - start, 2)
    return report


def _copy_metadata(doc: Document, entry: ManifestEntry) -> None:
    doc.doc_type = entry.doc_type
    doc.title = entry.title
    doc.source_url = entry.source_url
    doc.issued_on = entry.issued_on
    doc.effective_from = entry.effective_from
    doc.effective_to = entry.effective_to
