"""매매일지: AI 판단의 한 문장·근거, 지우거나 다시 시작한 봇의 일지 보관

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_judgments", sa.Column("decision", sa.Text(), nullable=True))
    op.add_column("ai_judgments", sa.Column("basis", postgresql.JSONB(), nullable=True))
    op.create_table(
        "journal_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="SET NULL")),
        sa.Column("bot_name", sa.String(50), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("why", sa.String(10), nullable=False),
        sa.Column("first_date", sa.Date(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=False),
        sa.Column("days", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_journal_archives_bot", "journal_archives", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_journal_archives_bot", "journal_archives")
    op.drop_table("journal_archives")
    op.drop_column("ai_judgments", "basis")
    op.drop_column("ai_judgments", "decision")
