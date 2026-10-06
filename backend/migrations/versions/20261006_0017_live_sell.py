"""live sell: 실제 주문에 파는 주문 (실거래 R3)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_orders", sa.Column("side", sa.String(4), nullable=False, server_default="BUY")
    )
    op.add_column("live_orders", sa.Column("quantity", sa.Numeric(), nullable=True))


def downgrade() -> None:
    op.drop_column("live_orders", "quantity")
    op.drop_column("live_orders", "side")
