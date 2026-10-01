"""Worker가 쓰는 시세 공급원. 토스(운영)와 DB 저장분(로컬·replay) 두 가지."""

from datetime import date, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from quant_lab.adapters.toss.client import TossClient
from quant_lab.application.bar_sync import SyncResult, sync_daily_bars
from quant_lab.domain.bars import TradingCalendar


class MarketData(Protocol):
    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult | None:
        """최신 완료 봉을 DB에 반영한다. None이면 저장된 봉만 쓴다."""
        ...

    def confirm_session(self, day: date) -> bool | None:
        """토스 기준으로 day가 미국 정규장 거래일인지. None이면 확인하지 않는다."""
        ...


class TossMarket:
    def __init__(self, client: TossClient, calendar: TradingCalendar) -> None:
        self.client = client
        self.calendar = calendar

    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult:
        return sync_daily_bars(self.client, session, self.calendar, symbol, now)

    def confirm_session(self, day: date) -> bool:
        today = self.client.us_market_calendar(day)["today"]
        return str(today.get("date")) == day.isoformat() and today.get("regularMarket") is not None


class StoredMarket:
    """토스를 호출하지 않는다. client가 계정당 1개라 로컬 개발은 기본적으로 이 모드다."""

    def refresh(self, session: Session, symbol: str, now: datetime) -> None:
        return None

    def confirm_session(self, day: date) -> None:
        return None
