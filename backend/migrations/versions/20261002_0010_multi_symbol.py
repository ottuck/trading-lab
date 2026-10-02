"""multi symbol: 봇 하나가 여러 종목(최대 10개)을 한 계좌로 다룬다

- bots.symbols: [{"symbol", "weight"}] (합 100). 기존 봇은 [{symbol, 100}]
- bot_positions: 종목별 보유 수량·평균 단가 (bot_accounts의 qty·avg_cost를 옮긴다)
- sim_orders.symbol, 대기 주문 유일 인덱스를 봇·종목 단위로

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("symbols", JSONB(), nullable=True))
    op.execute(
        "UPDATE bots SET symbols = "
        "jsonb_build_array(jsonb_build_object('symbol', symbol, 'weight', 100))"
    )
    op.alter_column("bots", "symbols", nullable=False)

    op.create_table(
        "bot_positions",
        sa.Column("bot_id", sa.Integer, sa.ForeignKey("bots.id"), primary_key=True),
        sa.Column("symbol", sa.String(20), primary_key=True),
        sa.Column("qty", sa.Numeric(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(), nullable=False),
    )
    op.execute(
        "INSERT INTO bot_positions (bot_id, symbol, qty, avg_cost) "
        "SELECT a.bot_id, b.symbol, a.qty, a.avg_cost "
        "FROM bot_accounts a JOIN bots b ON b.id = a.bot_id "
        "WHERE a.qty > 0"
    )
    op.drop_column("bot_accounts", "qty")
    op.drop_column("bot_accounts", "avg_cost")

    # 여러 종목 백테스트의 종목·비율 (한 종목이면 NULL)
    op.add_column("backtests", sa.Column("symbols", JSONB(), nullable=True))

    op.add_column("sim_orders", sa.Column("symbol", sa.String(20), nullable=True))
    op.execute("UPDATE sim_orders o SET symbol = b.symbol FROM bots b WHERE b.id = o.bot_id")
    op.alter_column("sim_orders", "symbol", nullable=False)
    op.drop_index("uq_sim_orders_pending", table_name="sim_orders")
    op.create_index(
        "uq_sim_orders_pending",
        "sim_orders",
        ["bot_id", "symbol"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    # 여러 종목 봇은 첫 종목만 남는다.
    op.drop_index("uq_sim_orders_pending", table_name="sim_orders")
    op.create_index(
        "uq_sim_orders_pending",
        "sim_orders",
        ["bot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.drop_column("sim_orders", "symbol")
    op.add_column(
        "bot_accounts", sa.Column("qty", sa.Numeric(), nullable=False, server_default="0")
    )
    op.add_column(
        "bot_accounts", sa.Column("avg_cost", sa.Numeric(), nullable=False, server_default="0")
    )
    op.execute(
        "UPDATE bot_accounts a SET qty = p.qty, avg_cost = p.avg_cost FROM bot_positions p "
        "JOIN bots b ON b.id = p.bot_id AND b.symbol = p.symbol WHERE p.bot_id = a.bot_id"
    )
    op.drop_table("bot_positions")
    op.drop_column("backtests", "symbols")
    op.drop_column("bots", "symbols")
