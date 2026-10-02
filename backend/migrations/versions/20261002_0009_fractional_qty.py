"""fractional qty: 모의 체결 수량을 소수점 6자리까지 (토스 금액 주문과 같은 방식)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 정수 → numeric. 기존 값(정수 주식)은 그대로 보존된다.
    op.alter_column("bot_accounts", "qty", type_=sa.Numeric(), postgresql_using="qty::numeric")
    op.alter_column("sim_orders", "qty", type_=sa.Numeric(), postgresql_using="qty::numeric")


def downgrade() -> None:
    # 소수점 수량은 버림된다.
    op.alter_column("sim_orders", "qty", type_=sa.Integer(), postgresql_using="floor(qty)::integer")
    op.alter_column(
        "bot_accounts", "qty", type_=sa.Integer(), postgresql_using="floor(qty)::integer"
    )
