"""API 응답 모델. 금액은 Decimal 그대로 내보낸다 (JSON에서는 문자열)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from quant_lab.domain.bot import CommandKind


class AccountView(BaseModel):
    initial_cash: Decimal
    cash: Decimal
    qty: int
    avg_cost: Decimal
    realized_pnl: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    equity: Decimal | None
    total_return: Decimal | None


class DecisionView(BaseModel):
    id: int
    session_date: date
    action: str
    target_long: bool
    holding: bool
    reason: str
    indicators: dict[str, Any]
    blocked: str | None
    created_at: datetime


class OrderView(BaseModel):
    id: int
    side: str
    status: str
    signal_date: date
    fill_date: date | None
    qty: int | None
    price: Decimal | None
    commission: Decimal | None
    realized_pnl: Decimal | None
    note: str | None


class RunView(BaseModel):
    id: uuid.UUID
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    session_date: date | None
    status: str
    detail: str | None


class BotView(BaseModel):
    id: int
    name: str
    symbol: str
    strategy: str
    params: dict[str, Any]
    state: str
    state_reason: str | None
    commission_rate: Decimal
    slippage_bps: Decimal
    risk: dict[str, Any]
    next_evaluation_at: datetime | None
    account: AccountView
    last_decision: DecisionView | None
    pending_order: OrderView | None
    last_run: RunView | None
    data_latest_date: date | None
    data_fetched_at: datetime | None


class EventView(BaseModel):
    id: int
    at: datetime
    level: str
    kind: str
    message: str
    bot_id: int | None
    run_id: uuid.UUID | None
    data: dict[str, Any] | None


class BarView(BaseModel):
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class CommandRequest(BaseModel):
    kind: CommandKind


class CommandAccepted(BaseModel):
    id: int
    bot_id: int
    kind: CommandKind
    created_at: datetime


class BacktestSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    symbol: str
    strategy: str
    params: dict[str, Any]
    metrics: dict[str, Any]


class BacktestDetail(BacktestSummary):
    data_start: date
    data_end: date
    initial_cash: Decimal
    commission_rate: Decimal
    slippage_bps: Decimal
    risk: dict[str, Any]
    fills: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    equity: list[dict[str, Any]]


class WorkerStatus(BaseModel):
    alive: bool
    worker_id: str | None
    last_seen_at: datetime | None


class HealthResponse(BaseModel):
    version: str
    db: Literal["ok", "down"]
    worker: WorkerStatus | None


class StrategyInfo(BaseModel):
    name: str
    default_params: dict[str, int]


class BacktestRequest(BaseModel):
    symbol: str
    strategy: str
    params: dict[str, int] = {}
    start: date | None = None
    end: date | None = None
    initial_cash: Decimal = Decimal(10_000)
    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)


class BotConfig(BaseModel):
    """봇의 전략·비용·위험 한도. 바꾸면 이후 판단부터 적용되고 이력은 이벤트로 남는다."""

    strategy: str
    params: dict[str, int] = {}
    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)
    max_position_value: Decimal | None = None
    max_order_value: Decimal | None = None


class BotCreate(BotConfig):
    name: str
    symbol: str
    initial_cash: Decimal = Decimal(10_000)
