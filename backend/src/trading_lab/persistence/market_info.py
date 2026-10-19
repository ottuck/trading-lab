"""종목 정보(레버리지 배수)와 최신 현재가 저장소."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from trading_lab.domain.bars import DailyBar
from trading_lab.domain.broker import ExchangeRate, Instrument, Quote
from trading_lab.persistence.models import ExchangeRateRow, InstrumentRow, LiveBarRow, QuoteRow


def upsert_instruments(session: Session, infos: Sequence[Instrument], now: datetime) -> None:
    for s in infos:
        row = {
            "symbol": s.symbol,
            "name": s.name,
            "security_type": s.security_type,
            "leverage_factor": s.leverage_factor,
            "updated_at": now,
        }
        stmt = insert(InstrumentRow).values(row)
        session.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=stmt.excluded))


def leverage_of(session: Session, symbol: str) -> Decimal | None:
    return session.scalar(
        select(InstrumentRow.leverage_factor).where(InstrumentRow.symbol == symbol)
    )


def upsert_quotes(session: Session, quotes: Sequence[Quote], now: datetime) -> None:
    for q in quotes:
        row = {"symbol": q.symbol, "price": q.price, "quoted_at": q.quoted_at, "fetched_at": now}
        stmt = insert(QuoteRow).values(row)
        session.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=stmt.excluded))


def upsert_live_bars(session: Session, bars: Sequence[DailyBar], now: datetime) -> None:
    for b in bars:
        row = {
            "symbol": b.symbol,
            "session_date": b.session_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "fetched_at": now,
        }
        stmt = insert(LiveBarRow).values(row)
        session.execute(stmt.on_conflict_do_update(index_elements=["symbol"], set_=stmt.excluded))


def upsert_exchange_rate(session: Session, fx: ExchangeRate, source: str, now: datetime) -> None:
    row = {
        "base": fx.base,
        "quote": fx.quote,
        "mid_rate": fx.mid_rate,
        "buy_rate": fx.buy_rate,
        "as_of": fx.as_of,
        "source": source,
        "fetched_at": now,
    }
    stmt = insert(ExchangeRateRow).values(row)
    session.execute(
        stmt.on_conflict_do_update(index_elements=["base", "quote"], set_=stmt.excluded)
    )


def instrument_map(session: Session) -> dict[str, InstrumentRow]:
    return {r.symbol: r for r in session.scalars(select(InstrumentRow))}


def quote_map(session: Session) -> dict[str, QuoteRow]:
    return {q.symbol: q for q in session.scalars(select(QuoteRow))}


def known_instrument_symbols(session: Session, symbols: Sequence[str]) -> set[str]:
    """종목 정보가 이미 저장된 종목."""
    return set(
        session.scalars(select(InstrumentRow.symbol).where(InstrumentRow.symbol.in_(symbols)))
    )
