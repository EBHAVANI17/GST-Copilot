"""Add chunks.section and documents.chunker for structure-aware chunking.

Revision ID: 0003
Revises: 0002
Create Date: M2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("section", sa.String(20), nullable=True))
    # NULL for documents indexed before M2, so the next ingest re-chunks them.
    op.add_column("documents", sa.Column("chunker", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "chunker")
    op.drop_column("chunks", "section")
