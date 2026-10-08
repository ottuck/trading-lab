"""유명 전략 4종을 없앴다: 그 전략으로 저장해 둔 시험 결과를 지운다

시험 결과는 일봉으로 다시 계산할 수 있는 값이라 지워도 잃는 것이 없다 (봇은 건드리지 않는다).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM backtests WHERE strategy IN ('sma_cross', 'trend_filter', 'rsi2', 'donchian')"
    )


def downgrade() -> None:
    pass
