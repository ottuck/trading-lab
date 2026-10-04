"""live reconcile: 실제 계좌 대조 결과 (보유가 봇이 산 수량보다 적은 종목)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("live_control", sa.Column("shortfall", JSONB(), nullable=True))
    op.add_column(
        "live_control", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("live_control", "checked_at")
    op.drop_column("live_control", "shortfall")
