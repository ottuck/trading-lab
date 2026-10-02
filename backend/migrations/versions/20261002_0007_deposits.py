"""deposits: 정기 입금(모으기 전략), 넣은 돈, 매수 예산

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 넣은 돈(시작 금액 + 입금). 기존 봇은 입금이 없었으므로 시작 금액과 같다.
    op.add_column("bot_accounts", sa.Column("contributed", sa.Numeric(), nullable=True))
    op.execute(
        "UPDATE bot_accounts a SET contributed = b.initial_cash FROM bots b WHERE b.id = a.bot_id"
    )
    op.alter_column("bot_accounts", "contributed", nullable=False)
    # 모으기 전략의 매수 예산. NULL이면 가진 현금 전부 (보통 전략)
    op.add_column("sim_orders", sa.Column("budget", sa.Numeric(), nullable=True))
    # 한 봇에 한 달 한 번만 입금한다 (Worker가 둘 떠도 중복 입금 없음)
    op.create_table(
        "bot_deposits",
        sa.Column("bot_id", sa.Integer, sa.ForeignKey("bots.id"), primary_key=True),
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("session_date", sa.Date, nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("bot_deposits")
    op.drop_column("sim_orders", "budget")
    op.drop_column("bot_accounts", "contributed")
