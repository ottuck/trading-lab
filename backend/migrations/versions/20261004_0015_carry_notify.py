"""carry and notify: 작은 실제 주문 몫 모아 사기, 텔레그램 알림 설정

- live_orders.carried_into: 모아 둔 몫(reason=carried)이 더해진 주문
- 예전 "too_small"로 넘긴 몫은 모아 둔 것으로 바꿔 다음 주문에 더한다
- notify_settings: 화면에서 켜고 고르는 알림 설정 1행

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("live_orders", sa.Column("carried_into", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE live_orders SET reason = 'carried' WHERE state = 'SKIPPED' AND reason = 'too_small'"
    )
    op.create_table(
        "notify_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scope", sa.String(10), nullable=False, server_default="live"),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notify_settings")
    op.drop_column("live_orders", "carried_into")
