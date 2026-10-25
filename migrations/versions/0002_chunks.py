"""Create the chunks table with a vector column and an HNSW index.

Revision ID: 0002
Revises: 0001
Create Date: M1
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # 384 = output size of BAAI/bge-small-en-v1.5. A different model needs a new migration.
        sa.Column("embedding", Vector(384), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_doc_index"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    # HNSW: approximate nearest-neighbour index, so similarity search stays fast
    # as the number of chunks grows. vector_cosine_ops = index for cosine distance (<=>).
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("chunks")
