"""backtests dedupe: 같은 조건의 지난 시험은 가장 최근 것만 남긴다

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 앞으로는 저장할 때 지운다 (persistence/backtests.py). 이미 쌓인 것을 한 번 정리한다.
    op.execute(
        """
        DELETE FROM backtests b USING backtests n
        WHERE b.id <> n.id
          AND b.symbol = n.symbol
          AND b.symbols IS NOT DISTINCT FROM n.symbols
          AND b.strategy = n.strategy
          AND b.params = n.params
          AND b.initial_cash = n.initial_cash
          AND b.commission_rate = n.commission_rate
          AND b.slippage_bps = n.slippage_bps
          AND b.risk = n.risk
          AND left(b.metrics->>'start', 7) = left(n.metrics->>'start', 7)
          AND (b.created_at < n.created_at OR (b.created_at = n.created_at AND b.id < n.id))
        """
    )


def downgrade() -> None:
    pass  # 지운 시험은 되살릴 수 없다
