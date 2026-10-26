"""ask_logs: one row per question asked through the API (observability, M3).

Revision ID: 0005
Revises: 0004
Create Date: M3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ask_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("request_id", sa.String(64)),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("search_query", sa.Text()),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("answer", sa.Text()),
        sa.Column("refused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("partial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cited", JSONB(), nullable=False, server_default="[]"),
        sa.Column("invalid_citations", JSONB(), nullable=False, server_default="[]"),
        sa.Column("retrieved", JSONB(), nullable=False, server_default="[]"),
        sa.Column("context_refs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("timings_ms", JSONB(), nullable=False, server_default="{}"),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(20)),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("feedback", sa.Integer()),
        sa.Column("feedback_note", sa.Text()),
        sa.CheckConstraint("feedback IN (-1, 1)", name="ck_ask_logs_feedback"),
    )
    op.create_index("ix_ask_logs_created_at", "ask_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("ask_logs")
