"""bots and dry run

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("initial_cash", sa.Numeric(), nullable=False),
        sa.Column("commission_rate", sa.Numeric(), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(), nullable=False),
        sa.Column("risk", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_evaluation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "bot_accounts",
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("cash", sa.Numeric(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Numeric(), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.PrimaryKeyConstraint("bot_id"),
    )
    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=20), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("target_long", sa.Boolean(), nullable=False),
        sa.Column("holding", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("indicators", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("blocked", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bot_id", "symbol", "session_date", "mode", name="uq_decision_bar"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sim_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bot_id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fill_date", sa.Date(), nullable=True),
        sa.Column("qty", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(), nullable=True),
        sa.Column("commission", sa.Numeric(), nullable=True),
        sa.Column("realized_pnl", sa.Numeric(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["bot_id"],
            ["bots.id"],
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index("ix_runs_bot_started", "runs", ["bot_id", "started_at"])
    op.create_index("ix_events_at", "events", ["at"])
    op.create_index(
        "ix_commands_pending",
        "commands",
        ["created_at"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )
    # 봇마다 대기 중인 모의 주문은 최대 하나
    op.create_index(
        "uq_sim_orders_pending",
        "sim_orders",
        ["bot_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sim_orders_pending", table_name="sim_orders")
    op.drop_index("ix_commands_pending", table_name="commands")
    op.drop_index("ix_events_at", table_name="events")
    op.drop_index("ix_runs_bot_started", table_name="runs")
    op.drop_table("sim_orders")
    op.drop_table("events")
    op.drop_table("decisions")
    op.drop_table("runs")
    op.drop_table("commands")
    op.drop_table("bot_accounts")
    op.drop_table("bots")
