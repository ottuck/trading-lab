"""기존 AI 봇 이름을 "시장분석 AI 봇"으로: 캔들분석 AI 봇이 생겨 "AI 봇"만으로는 구분되지 않는다

이름표만 바꾼다 (전략·기록은 그대로). 이름을 직접 지은 봇과, 같은 이름이 이미 있으면 두지 않는다.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE bots SET name = '시장분석 AI 봇'
        WHERE strategy = 'ai_judge' AND name = 'AI 봇'
          AND NOT EXISTS (SELECT 1 FROM bots WHERE name = '시장분석 AI 봇')
        """
    )


def downgrade() -> None:
    pass
