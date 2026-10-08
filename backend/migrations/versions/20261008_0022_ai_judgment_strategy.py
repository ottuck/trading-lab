"""ai_judgments.strategy: 한 달 AI 비용 상한을 전략(시장분석·캔들분석)마다 따로 센다

지금까지의 판단은 모두 시장분석 AI 봇(ai_judge)과 그 시험 판단이다.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_judgments",
        sa.Column("strategy", sa.String(20), nullable=False, server_default="ai_judge"),
    )
    op.alter_column("ai_judgments", "strategy", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_judgments", "strategy")
