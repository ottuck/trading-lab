"""Worker가 쓰는 시세 공급원. 토스(운영)와 DB 저장분(로컬·replay) 두 가지."""

from datetime import date, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from quant_lab.adapters.toss.client import Quote, StockInfo, TossClient
from quant_lab.application.bar_sync import SyncResult, sync_daily_bars
from quant_lab.domain.bars import DailyBar, TradingCalendar, outlier_limit
from quant_lab.persistence.market_info import leverage_of


class MarketData(Protocol):
    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult | None:
        """최신 완료 봉을 DB에 반영한다. None이면 저장된 봉만 쓴다."""
        ...

    def confirm_session(self, day: date) -> bool | None:
        """토스 기준으로 day가 미국 정규장 거래일인지. None이면 확인하지 않는다."""
        ...


class LiveSource(Protocol):
    """화면 표시용 실시간 정보. 판단에는 쓰지 않는다."""

    def instruments(self, symbols: list[str]) -> list[StockInfo]: ...

    def quotes(self, symbols: list[str]) -> list[Quote]: ...

    def live_bars(self, symbols: list[str]) -> list[DailyBar]: ...


class TossMarket:
    def __init__(self, client: TossClient, calendar: TradingCalendar) -> None:
        self.client = client
        self.calendar = calendar

    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult:
        limit = outlier_limit(leverage_of(session, symbol))
        return sync_daily_bars(
            self.client, session, self.calendar, symbol, now, max_abs_return=limit
        )

    def instruments(self, symbols: list[str]) -> list[StockInfo]:
        return self.client.stocks(symbols)

    def quotes(self, symbols: list[str]) -> list[Quote]:
        return self.client.prices(symbols)

    def live_bars(self, symbols: list[str]) -> list[DailyBar]:
        """종목마다 가장 최근 일봉 1개 (진행 중이면 정규장 전 거래부터 채워진 값)."""
        return [b for s in symbols for b in self.client.daily_candles(s, count=1).bars[-1:]]

    def confirm_session(self, day: date) -> bool:
        today = self.client.us_market_calendar(day)["today"]
        return str(today.get("date")) == day.isoformat() and today.get("regularMarket") is not None


class StoredMarket:
    """토스를 호출하지 않는다. client가 계정당 1개라 로컬 개발은 기본적으로 이 모드다."""

    def refresh(self, session: Session, symbol: str, now: datetime) -> None:
        return None

    def confirm_session(self, day: date) -> None:
        return None
