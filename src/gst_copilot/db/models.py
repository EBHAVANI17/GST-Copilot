"""Database tables, as SQLAlchemy models.

M0 only defines `documents`: one row per official source document
(an Act, a rule, a notification, a circular). Chunks and vectors come in M1.
The migration in migrations/versions/ creates the same table; when you
change a model, write a new migration (alembic revision --autogenerate).
"""

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Must match settings.embedding_dim and the VECTOR(n) column in migration 0002.
EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("doc_id", name="uq_documents_doc_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Our own stable ID, used in citations, e.g. "CGST-ACT-2017" or "NOTIF-9-2025-CTR"
    doc_id: Mapped[str] = mapped_column(String(100))
    doc_type: Mapped[str] = mapped_column(String(20))  # act | rule | notification | circular
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    sha256: Mapped[str] = mapped_column(String(64))  # detects when a source file changes
    # How the document was chunked, e.g. "section-v1-1200-200". A different value
    # means the chunking code or settings changed, so ingest re-chunks it.
    chunker: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    """A piece of a document's text plus its embedding vector.

    M2: one section or rule per chunk (long ones split at sub-sections), with the
    section number stored so evaluation can check the right section was found.
    """

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)  # position within the document
    text: Mapped[str] = mapped_column(Text)
    section: Mapped[str | None] = mapped_column(String(20))  # "16", "43A"; None if unknown
    # Words of `text` for keyword search, computed by Postgres (migration 0004).
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
