import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, String, Uuid
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
