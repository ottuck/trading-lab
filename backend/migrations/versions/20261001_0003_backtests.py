"""backtests

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtests",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_version", sa.String(50), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("params", postgresql.JSONB, nullable=False),
        sa.Column("data_start", sa.Date, nullable=False),
        sa.Column("data_end", sa.Date, nullable=False),
        sa.Column("initial_cash", sa.Numeric(), nullable=False),
        sa.Column("commission_rate", sa.Numeric(), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(), nullable=False),
        sa.Column("risk", postgresql.JSONB, nullable=False),
        sa.Column("metrics", postgresql.JSONB, nullable=False),
        sa.Column("fills", postgresql.JSONB, nullable=False),
        sa.Column("actions", postgresql.JSONB, nullable=False),
        sa.Column("equity", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_backtests_symbol_created", "backtests", ["symbol", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_backtests_symbol_created", table_name="backtests")
    op.drop_table("backtests")
