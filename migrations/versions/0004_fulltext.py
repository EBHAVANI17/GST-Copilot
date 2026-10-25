"""Full-text search column and index on chunks, for hybrid retrieval.

Revision ID: 0004
Revises: 0003
Create Date: M2
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A generated column: Postgres keeps it in sync with `text` on every insert/update,
    # and fills it for existing rows now. 'english' = stemming ("credits" -> "credit")
    # and stop words ("the", "of") removed.
    op.execute(
        "ALTER TABLE chunks ADD COLUMN tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    # GIN: an inverted index (word -> rows containing it), like a book's index.
    op.execute("CREATE INDEX ix_chunks_tsv ON chunks USING gin (tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX ix_chunks_tsv")
    op.execute("ALTER TABLE chunks DROP COLUMN tsv")
