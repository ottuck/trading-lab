"""reserve: 모으기 전략이 고점 때 모아 둔 돈 (하락장에만 쓴다)

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bot_accounts", sa.Column("reserve", sa.Numeric(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("bot_accounts", "reserve")
