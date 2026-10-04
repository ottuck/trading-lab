"""exchange rates: 통화 쌍마다 최신 환율 1행 (W1 원화로 보기)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_rates",
        sa.Column("base", sa.String(3), primary_key=True),
        sa.Column("quote", sa.String(3), primary_key=True),
        sa.Column("mid_rate", sa.Numeric(), nullable=False),
        sa.Column("buy_rate", sa.Numeric(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("exchange_rates")
