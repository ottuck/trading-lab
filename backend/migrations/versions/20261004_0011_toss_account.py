"""toss account snapshot

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "toss_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cash_usd", sa.Numeric(), nullable=True),
        sa.Column("cash_krw", sa.Numeric(), nullable=True),
        sa.Column("holdings", JSONB(), nullable=False),
        sa.Column("orders", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("toss_account")
