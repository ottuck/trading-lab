import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 가격·수량은 float를 쓰지 않는다 (project.md 3절 원칙 7).
PRICE = Numeric()  # 정밀도 제한 없이 토스 값을 그대로 저장한다 (반올림 시 수정주가 비교가 틀어짐)
VOLUME = Numeric()


class Base(DeclarativeBase):
    pass


class WorkerHeartbeat(Base):
    """Worker 프로세스 생존 기록. 봇 상태와는 별개다."""

    __tablename__ = "worker_heartbeat"

    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BacktestRow(Base):
    """백테스트 1회. 같은 조건으로 다시 실행할 수 있게 입력 조건을 모두 저장한다 (원칙 9)."""

    __tablename__ = "backtests"
    __table_args__ = (Index("ix_backtests_symbol_created", "symbol", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    code_version: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(20))
    strategy: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_start: Mapped[date] = mapped_column(Date)
    data_end: Mapped[date] = mapped_column(Date)
    initial_cash: Mapped[Decimal] = mapped_column(PRICE)
    commission_rate: Mapped[Decimal] = mapped_column(PRICE)
    slippage_bps: Mapped[Decimal] = mapped_column(PRICE)
    risk: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fills: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    equity: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)


class DailyBarRow(Base):
    """완료된 미국 일봉 캐시 (수정주가). 토스 데이터이므로 외부로 내보내지 않는다."""

    __tablename__ = "daily_bars"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[Decimal] = mapped_column(VOLUME)
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BotRow(Base):
    """DRY RUN 봇 1개 = 종목 1개 + 전략 1개.

    판단 기록(decisions.strategy)에 당시 전략·파라미터 스냅샷을 남긴다.
    """

    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)
    symbol: Mapped[str] = mapped_column(String(20))
    strategy: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20))
    state_reason: Mapped[str | None] = mapped_column(Text)
    initial_cash: Mapped[Decimal] = mapped_column(PRICE)
    commission_rate: Mapped[Decimal] = mapped_column(PRICE)
    slippage_bps: Mapped[Decimal] = mapped_column(PRICE)
    risk: Mapped[dict[str, Any]] = mapped_column(JSONB)
    next_evaluation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BotAccountRow(Base):
    """봇의 모의 현금·포지션. 실제 토스 계좌와 무관하다."""

    __tablename__ = "bot_accounts"

    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), primary_key=True)
    cash: Mapped[Decimal] = mapped_column(PRICE)
    qty: Mapped[int] = mapped_column(Integer)
    avg_cost: Mapped[Decimal] = mapped_column(PRICE)
    realized_pnl: Mapped[Decimal] = mapped_column(PRICE)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CommandRow(Base):
    """화면(API)이 쓰고 Worker가 처리하는 명령."""

    __tablename__ = "commands"
    __table_args__ = (
        Index("ix_commands_pending", "created_at", postgresql_where=text("processed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"))
    kind: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)


class RunRow(Base):
    """평가 1회."""

    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_bot_started", "bot_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"))
    trigger: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str | None] = mapped_column(Text)


class DecisionRow(Base):
    """완료 봉 하나에 대한 판단. 유일 키가 중복 모의 주문을 막는다 (project.md 3절 원칙 4)."""

    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("bot_id", "symbol", "session_date", "mode", name="uq_decision_bar"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    session_date: Mapped[date] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id"))
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(String(10))
    target_long: Mapped[bool] = mapped_column(Boolean)
    holding: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONB)
    blocked: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SimOrderRow(Base):
    """모의 주문. 판단 하나에 최대 하나."""

    __tablename__ = "sim_orders"
    __table_args__ = (
        Index(
            "uq_sim_orders_pending",
            "bot_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"))
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"), unique=True)
    side: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    signal_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fill_date: Mapped[date | None] = mapped_column(Date)
    qty: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[Decimal | None] = mapped_column(PRICE)
    commission: Mapped[Decimal | None] = mapped_column(PRICE)
    realized_pnl: Mapped[Decimal | None] = mapped_column(PRICE)
    note: Mapped[str | None] = mapped_column(Text)


class EventRow(Base):
    """알림·최근 활동의 원본 기록."""

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_at", "at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    bot_id: Mapped[int | None] = mapped_column(ForeignKey("bots.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id"))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class InstrumentRow(Base):
    """관심 종목·봇 종목의 기본 정보. Worker가 토스 /stocks로 하루 한 번 갱신한다."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    security_type: Mapped[str] = mapped_column(String(20))
    leverage_factor: Mapped[Decimal | None] = mapped_column(PRICE)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuoteRow(Base):
    """종목별 최신 현재가 (화면 표시용). 판단에는 쓰지 않는다 (완료 일봉만 사용)."""

    __tablename__ = "quotes"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    price: Mapped[Decimal] = mapped_column(PRICE)
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
