"""Database tables, as SQLAlchemy models.

M0 only defines `documents`: one row per official source document
(an Act, a rule, a notification, a circular). Chunks and vectors come in M1.
The migration in migrations/versions/ creates the same table; when you
change a model, write a new migration (alembic revision --autogenerate).
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
