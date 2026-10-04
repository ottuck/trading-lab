"""API 응답 모델. 금액은 Decimal 그대로 내보낸다 (JSON에서는 문자열)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from quant_lab.domain.bot import CommandKind


class PositionView(BaseModel):
    """종목 하나의 보유와 평가 (장 마감 기준 + 있으면 실시간)."""

    symbol: str
    weight: int  # 봇의 종목 비율 (봇에서 빠진 종목이면 0)
    qty: Decimal
    avg_cost: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    live_price: Decimal | None = None
    live_at: datetime | None = None
    live_change: Decimal | None = None


class AccountView(BaseModel):
    """봇 계좌. qty·avg_cost·last_close·live_price·live_change는 대표 종목(첫 종목) 값이고,
    market_value·unrealized_pnl·equity·live_equity·live_unrealized_pnl은 모든 종목 합계다."""

    initial_cash: Decimal
    cash: Decimal
    qty: Decimal
    avg_cost: Decimal
    realized_pnl: Decimal
    last_close: Decimal | None
    last_close_date: date | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    equity: Decimal | None
    total_return: Decimal | None  # 넣은 돈 대비
    contributed: Decimal  # 넣은 돈 (시작 금액 + 정기 입금)
    # 실시간(화면 표시용). 판단·주간 리포트는 위의 장 마감 기준 값을 쓴다.
    live_price: Decimal | None = None
    live_at: datetime | None = None
    live_change: Decimal | None = None  # 마지막 장 마감 가격 대비
    live_equity: Decimal | None = None
    live_unrealized_pnl: Decimal | None = None
    reserve: Decimal = Decimal(0)  # 모으기 전략이 고점 때 모아 둔 돈
    positions: list[PositionView] = []


class InstrumentView(BaseModel):
    symbol: str
    name: str | None
    leverage_factor: Decimal | None
    live_price: Decimal | None
    live_at: datetime | None


class FxView(BaseModel):
    """화면 원화 환산용 원/달러 매매기준율 (W1). 계산·주문은 늘 달러다."""

    base: str
    quote: str
    rate: Decimal
    as_of: datetime
    source: str  # 출처 코드 (demo면 예시 환율)


class BrokerHoldingView(BaseModel):
    symbol: str
    name: str
    currency: str
    qty: Decimal
    avg_price: Decimal
    last_price: Decimal
    value: Decimal


class BrokerOrderView(BaseModel):
    symbol: str
    side: str
    status: str
    currency: str
    ordered_at: datetime
    amount: Decimal | None
    qty: Decimal


class BrokerAccountView(BaseModel):
    """실제 증권사 계좌를 마지막으로 읽은 결과 (실거래 R1). 계좌번호는 없다."""

    source: str | None  # 증권사 출처 코드 (화면 이름은 frontend source.ts)
    cash_usd: Decimal | None
    cash_krw: Decimal | None
    holdings: list[BrokerHoldingView]
    orders: list[BrokerOrderView]
    fetched_at: datetime | None
    error: Literal["access", "temporary"] | None
    error_at: datetime | None


class DecisionView(BaseModel):
    id: int
    symbol: str
    session_date: date
    action: str
    target_long: bool
    holding: bool
    reason: str
    indicators: dict[str, Any]
    blocked: str | None
    created_at: datetime
    plain_reason: str = ""  # 일상어 설명
    plain_action: str = ""  # 예: "내일 장이 열리면 QQQ를 사요."


class OrderView(BaseModel):
    id: int
    symbol: str
    side: str
    status: str
    signal_date: date
    fill_date: date | None
    qty: Decimal | None
    price: Decimal | None
    commission: Decimal | None
    realized_pnl: Decimal | None
    note: str | None
    budget: Decimal | None = None  # 이 주문에 쓸 돈 (모으기 전략)


class RunView(BaseModel):
    id: uuid.UUID
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    session_date: date | None
    status: str
    detail: str | None


class SymbolWeight(BaseModel):
    symbol: str
    weight: int  # 비율(%) — 봇의 종목 비율 합은 100


class BotView(BaseModel):
    id: int
    name: str
    symbol: str  # 대표 종목 (첫 종목)
    symbols: list[SymbolWeight]
    strategy: str
    params: dict[str, Any]
    state: str
    state_reason: str | None
    commission_rate: Decimal
    slippage_bps: Decimal
    risk: dict[str, Any]
    next_evaluation_at: datetime | None
    account: AccountView
    last_decision: DecisionView | None  # 대표 종목의 마지막 판단
    last_decisions: list[DecisionView] = []  # 마지막 판단일의 종목별 판단
    pending_order: OrderView | None
    pending_orders: list[OrderView] = []
    last_run: RunView | None
    data_latest_date: date | None
    data_fetched_at: datetime | None
    data_source: str | None
    live_ratio: Decimal | None = None  # 실제로 따라 사기 비율 (꺼짐이면 null)
    live_streak: int = 0


class LiveOrderView(BaseModel):
    """실제 주문 1건 (실거래 R2)."""

    id: int
    bot_id: int | None
    bot_name: str | None
    symbol: str
    signal_date: date
    trade_date: date
    amount: Decimal
    state: str  # WAITING_APPROVAL·APPROVED·SENDING·SENT·FILLED·CANCELED·REJECTED·SKIPPED·UNKNOWN
    reason: str | None
    filled_qty: Decimal | None
    filled_amount: Decimal | None
    carried_into: int | None = None  # 작아서 모아 둔 몫이 더해진 주문
    created_at: datetime
    updated_at: datetime


class LiveView(BaseModel):
    trader: str | None  # 실거래 스위치가 켜졌으면 증권사 출처 코드, 꺼졌으면 null
    halted: bool
    auto_after: int
    per_order: Decimal
    per_month: Decimal
    ratios: list[str]
    shortfall: list[dict[str, str]] = []  # 실제 계좌 대조 [{symbol, held, bought}]
    checked_at: datetime | None = None
    orders: list[LiveOrderView]


class LiveRatioUpdate(BaseModel):
    ratio: str | None  # "1/100" | "1/10" | null(끄기)


class NotifyView(BaseModel):
    available: bool  # Worker에 텔레그램 봇 정보가 있음
    enabled: bool
    scope: str  # live(실제 주문만) | all(모의 투자 소식까지)


class NotifyUpdate(BaseModel):
    enabled: bool
    scope: Literal["live", "all"]


class LiveHalt(BaseModel):
    halted: bool


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
    live: bool = False  # 진행 중인 오늘 봉 (아직 확정 아님)


class EquityPoint(BaseModel):
    date: date
    equity: Decimal
    contributed: Decimal  # 이날까지 넣은 돈
    benchmark: Decimal  # 같은 돈으로 그냥 들고 있었다면
    live: bool = False


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
    symbols: list[dict[str, Any]] | None = None  # 여러 종목이면 [{"symbol", "weight"}]
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
    demo: bool = False  # 예시 데이터로 보는 공개 데모


class PresetView(BaseModel):
    key: str
    label: str
    params: dict[str, int]


class ChoiceOption(BaseModel):
    value: int
    label: str


class ChoiceView(BaseModel):
    """프리셋과 따로 고르는 규칙 (예: 고점에 쉬기)."""

    key: str
    label: str
    options: list[ChoiceOption]
    hint: str
    requires: str = ""


class StrategyInfo(BaseModel):
    """화면용 전략 소개 (별명·쉬운 설명·성격·프리셋)."""

    name: str
    nickname: str
    summary: str
    risk: str
    trades: str
    presets: list[PresetView]
    default_params: dict[str, int]
    accumulates: bool = False  # 매달 입금하고 사 모으는 전략 (팔지 않음)
    preset_label: str = "반응 속도"
    choices: list[ChoiceView] = []


class ActivityItem(BaseModel):
    """사람이 읽는 활동 기록 (텔레그램과 같은 문장)."""

    id: int
    at: datetime
    icon: str
    title: str
    body: str
    level: str


class BacktestRequest(BaseModel):
    symbol: str
    symbols: list[SymbolWeight] | None = None  # 여러 종목(모으기 전략만, 비율 합 100)
    strategy: str
    params: dict[str, int] = {}
    start: date | None = None
    end: date | None = None
    initial_cash: Decimal | None = None  # 없으면 $10,000 (모으기 전략은 한 달 입금액)
    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)


class SymbolPlanView(BaseModel):
    symbol: str
    weight: int
    close: Decimal
    state: str  # dip · hot · wait · normal
    dip_price: Decimal
    hot_price: Decimal | None
    buy: Decimal
    save: Decimal


class ReserveItemView(BaseModel):
    month: str
    symbol: str
    amount: Decimal


class PlanView(BaseModel):
    """따라 하기: 나 카피 봇이 다음에 할 일 (지금 가격이 이어진다면)."""

    as_of: date
    deposit_date: date
    deposit: Decimal
    symbols: list[SymbolPlanView]
    reserve: Decimal
    reserve_items: list[ReserveItemView]


class ParallelRequest(BaseModel):
    """평행세계의 나 (나처럼 투자 전용). 시작 금액이 없으면 한 달 입금액."""

    symbol: str = ""
    symbols: list[SymbolWeight] | None = None
    params: dict[str, int] = {}
    start: date | None = None
    end: date | None = None
    initial_cash: Decimal | None = None


class WorldPoint(BaseModel):
    date: date
    equity: Decimal


class MonthBuy(BaseModel):
    month: str  # YYYY-MM
    bought: Decimal


class WorldView(BaseModel):
    key: str  # me(나), dca(매달 그냥 사기), 그 밖은 규칙을 하나 바꾼 나
    title: str
    params: dict[str, int] | None
    final_equity: Decimal
    contributed: Decimal
    cagr: Decimal  # 넣은 시점을 반영한 연 수익률 (XIRR)
    same_as_me: bool  # 이 기간에는 나와 결과가 같았다
    equity: list[WorldPoint]  # 달마다 마지막 날
    recent: list[MonthBuy]  # 지난달·이번 달에 산 금액 (월간 정리용)


class ParallelView(BaseModel):
    start: date | None
    end: date | None
    worlds: list[WorldView]
    note: str | None = None  # 계산하지 못한 이유 (예: 시작한 지 얼마 안 됨)


class BotConfig(BaseModel):
    """봇의 전략·비용·위험 한도. 바꾸면 이후 판단부터 적용되고 이력은 이벤트로 남는다."""

    strategy: str
    params: dict[str, int] = {}
    commission_rate: Decimal = Decimal("0.001")
    slippage_bps: Decimal = Decimal(5)
    max_position_value: Decimal | None = None
    max_order_value: Decimal | None = None


class SymbolsUpdate(BaseModel):
    """만든 뒤 종목·비율 바꾸기. 비율 합 100, 최대 10개."""

    symbols: list[SymbolWeight]


class BotRename(BaseModel):
    name: str


class BotCreate(BotConfig):
    name: str
    symbol: str  # 종목 하나. symbols가 있으면 그 첫 종목과 같아야 한다
    symbols: list[SymbolWeight] | None = None  # 여러 종목(최대 10개, 비율 합 100, 모으기 전략만)
    initial_cash: Decimal = Decimal(10_000)
