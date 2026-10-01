from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String
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
