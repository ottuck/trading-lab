"""화면 조회: 일봉(+ 진행 중 봉), 종목 목록, 최근 활동, 판단·주문·이벤트 기록.

DB만 읽는다 (증권사를 부르지 않음, project.md 3절 원칙 6). 필드 이름은 API 응답과 같다.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from trading_lab.application.messages import event_message
from trading_lab.persistence.bars import recent_bar_rows
from trading_lab.persistence.bots import (
    bot_weights,
    latest_decisions,
    latest_sim_orders,
    list_bots,
)
from trading_lab.persistence.events import event_log, latest_events
from trading_lab.persistence.market_info import instrument_map, quote_map
from trading_lab.persistence.models import (
    DecisionRow,
    EventRow,
    ExchangeRateRow,
    LiveBarRow,
    SimOrderRow,
)


@dataclass(frozen=True)
class Bar:
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    live: bool = False  # 진행 중인 오늘 봉 (아직 확정 아님)


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str
    name: str | None
    leverage_factor: Decimal | None
    live_price: Decimal | None
    live_at: datetime | None


@dataclass(frozen=True)
class FxInfo:
    base: str
    quote: str
    rate: Decimal  # 매매기준율
    as_of: datetime
    source: str


@dataclass(frozen=True)
class Activity:
    id: int
    at: datetime
    icon: str
    title: str
    body: str
    level: str


def price_bars(session: Session, symbol: str, start: date | None, limit: int) -> list[Bar]:
    """완료 봉, 그리고 그보다 새 날짜의 진행 중 봉이 있으면 끝에 붙인다 (차트 표시용)."""
    symbol = symbol.upper()
    rows = recent_bar_rows(session, symbol, start, limit)
    out = [Bar(r.session_date, r.open, r.high, r.low, r.close, r.volume) for r in reversed(rows)]
    lb = session.get(LiveBarRow, symbol)
    if lb is not None and (not out or lb.session_date > out[-1].date):
        out.append(Bar(lb.session_date, lb.open, lb.high, lb.low, lb.close, lb.volume, live=True))
    return out


def instruments(session: Session, watchlist: Sequence[str]) -> list[InstrumentInfo]:
    """관심 종목 + 봇 종목 (종목 버튼·레버리지 표시). 레버리지 배수는 Worker가 채운다."""
    symbols = list(watchlist)
    for bot in list_bots(session):
        symbols += [s for s in bot_weights(bot) if s not in symbols]
    infos = instrument_map(session)
    quotes = quote_map(session)
    return [
        InstrumentInfo(
            symbol=s,
            name=infos[s].name if s in infos else None,
            leverage_factor=infos[s].leverage_factor if s in infos else None,
            live_price=quotes[s].price if s in quotes else None,
            live_at=quotes[s].quoted_at if s in quotes else None,
        )
        for s in symbols
    ]


def usd_krw(session: Session) -> FxInfo | None:
    """화면 원화 환산용 최신 원/달러 (W1). Worker가 한 시간마다, 데모는 고정 예시 값."""
    row = session.get(ExchangeRateRow, ("USD", "KRW"))
    if row is None:
        return None
    return FxInfo(row.base, row.quote, row.mid_rate, row.as_of, row.source)


def activity(session: Session, bot_id: int | None, kind: str | None, limit: int) -> list[Activity]:
    """최근 활동을 쉬운 말로. 내부 기록(재시작, 중복 평가 등)은 빼고 보여준다."""
    bots = {b.id: b for b in list_bots(session)}
    items: list[Activity] = []
    for e in latest_events(session, limit * 5, bot_id=bot_id, kind=kind):
        bot = bots.get(e.bot_id) if e.bot_id else None
        msg = event_message(
            e.kind,
            e.level,
            e.message,
            e.data,
            bot.name if bot else None,
            bot.symbol if bot else None,
        )
        if msg is not None:
            items.append(Activity(e.id, e.at, msg.icon, msg.title, msg.body, msg.level))
        if len(items) >= limit:
            break
    return items


def events(
    session: Session, bot_id: int | None, level: str | None, kind: str | None, limit: int
) -> list[EventRow]:
    """원시 이벤트 기록 (화면에는 쓰지 않고 확인·디버깅용)."""
    return event_log(session, limit, bot_id=bot_id, level=level, kind=kind)


def decisions(session: Session, bot_id: int, limit: int) -> list[DecisionRow]:
    return latest_decisions(session, bot_id, limit)


def orders(session: Session, bot_id: int, limit: int) -> list[SimOrderRow]:
    return latest_sim_orders(session, bot_id, limit)
