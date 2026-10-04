"""live orders: 실제로 따라 사기 (실거래 R2)

- bots.live_ratio·live_since·live_streak
- live_orders: 모의 매수 1건에 실제 주문 최대 하나 (sim_order_id 유일, 중복 방지 키 유일)
- live_control: 비상 중지와 실거래 스위치 상태 1행

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("live_ratio", sa.Numeric(), nullable=True))
    op.add_column("bots", sa.Column("live_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "bots", sa.Column("live_streak", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "live_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        # 봇을 지우거나 처음부터 다시 시작해도 실제 주문 기록은 남긴다 (연결만 비움)
        sa.Column(
            "bot_id", sa.Integer(), sa.ForeignKey("bots.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "sim_order_id",
            sa.Integer(),
            sa.ForeignKey("sim_orders.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("key", sa.String(36), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), nullable=True),
        sa.Column("broker_order_id", sa.String(64), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filled_qty", sa.Numeric(), nullable=True),
        sa.Column("filled_amount", sa.Numeric(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_live_orders_state", "live_orders", ["state"])
    op.create_table(
        "live_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("halted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trader", sa.String(20), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("live_control")
    op.drop_index("ix_live_orders_state", "live_orders")
    op.drop_table("live_orders")
    op.drop_column("bots", "live_streak")
    op.drop_column("bots", "live_since")
    op.drop_column("bots", "live_ratio")
