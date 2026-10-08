"""drop live_streak: 처음 몇 번 승인받는 단계를 없앴다

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("bots", "live_streak")


def downgrade() -> None:
    op.add_column(
        "bots", sa.Column("live_streak", sa.Integer(), nullable=False, server_default="0")
    )
