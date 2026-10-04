"""broker account: toss_account를 증권사 중립 이름으로, 출처 코드 추가

엔진·저장소는 증권사를 모른다 (domain/broker.py). 실패는 종류 코드(access | temporary)로만 남긴다.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("toss_account", "broker_account")
    op.add_column("broker_account", sa.Column("source", sa.String(20), nullable=True))
    # 예전 실패 기록은 원문 메시지라 종류를 알 수 없다. 다음 읽기에서 다시 채워진다.
    op.execute("UPDATE broker_account SET error = NULL, error_at = NULL")


def downgrade() -> None:
    op.drop_column("broker_account", "source")
    op.rename_table("broker_account", "toss_account")
