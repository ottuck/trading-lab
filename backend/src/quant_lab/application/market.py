"""Worker가 쓰는 시세 공급원. 증권사 연결(운영)과 DB 저장분(로컬·replay) 두 가지."""

from datetime import date, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from quant_lab.application.bar_sync import SyncResult, sync_daily_bars
from quant_lab.domain.bars import DailyBar, TradingCalendar, outlier_limit
from quant_lab.domain.broker import Broker, ExchangeRate, Instrument, Quote
from quant_lab.persistence.market_info import leverage_of


class MarketData(Protocol):
    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult | None:
        """최신 완료 봉을 DB에 반영한다. None이면 저장된 봉만 쓴다."""
        ...

    def confirm_session(self, day: date) -> bool | None:
        """증권사 기준으로 day가 미국 정규장 거래일인지. None이면 확인하지 않는다."""
        ...


class LiveSource(Protocol):
    """화면 표시용 실시간 정보. 판단에는 쓰지 않는다."""

    def instruments(self, symbols: list[str]) -> list[Instrument]: ...

    def quotes(self, symbols: list[str]) -> list[Quote]: ...

    def live_bars(self, symbols: list[str]) -> list[DailyBar]: ...

    def exchange_rate(self, base: str, quote: str) -> ExchangeRate: ...

    @property
    def source(self) -> str: ...


class BrokerMarket:
    def __init__(self, broker: Broker, calendar: TradingCalendar) -> None:
        self.broker = broker
        self.calendar = calendar

    def refresh(self, session: Session, symbol: str, now: datetime) -> SyncResult:
        limit = outlier_limit(leverage_of(session, symbol))
        return sync_daily_bars(
            self.broker, session, self.calendar, symbol, now, max_abs_return=limit
        )

    def instruments(self, symbols: list[str]) -> list[Instrument]:
        return self.broker.instruments(symbols)

    def quotes(self, symbols: list[str]) -> list[Quote]:
        return self.broker.quotes(symbols)

    def live_bars(self, symbols: list[str]) -> list[DailyBar]:
        """종목마다 가장 최근 일봉 1개 (진행 중이면 정규장 전 거래부터 채워진 값)."""
        return [b for s in symbols if (b := self.broker.latest_daily_bar(s)) is not None]

    def exchange_rate(self, base: str, quote: str) -> ExchangeRate:
        return self.broker.exchange_rate(base, quote)

    @property
    def source(self) -> str:
        return self.broker.source

    def confirm_session(self, day: date) -> bool:
        return self.broker.is_regular_session(day)


class StoredMarket:
    """증권사를 호출하지 않는다. 토스는 client당 토큰이 1개라 로컬 개발은 기본적으로 이 모드다."""

    def refresh(self, session: Session, symbol: str, now: datetime) -> None:
        return None

    def confirm_session(self, day: date) -> None:
        return None
