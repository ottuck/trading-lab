"""ai judgments: AI 판단 기록 (마일스톤 4 A1)

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_judgments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="SET NULL")),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20)),
        sa.Column("model", sa.String(64)),
        sa.Column("prompt_version", sa.String(32)),
        sa.Column("request", postgresql.JSONB()),
        sa.Column("weights", postgresql.JSONB()),
        sa.Column("reasons", postgresql.JSONB()),
        sa.Column("summary", sa.Text()),
        sa.Column("sources", postgresql.JSONB()),
        sa.Column("queries", postgresql.JSONB()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("web_searches", sa.Integer()),
        sa.Column("cost", sa.Numeric()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bot_id", "session_date"),
    )


def downgrade() -> None:
    op.drop_table("ai_judgments")
