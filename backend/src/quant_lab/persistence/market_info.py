"""종목 정보(레버리지 배수)와 최신 현재가 저장소."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from quant_lab.adapters.toss.client import Quote, StockInfo
from quant_lab.domain.bars import DailyBar
from quant_lab.persistence.models import InstrumentRow, LiveBarRow, QuoteRow


def upsert_instruments(session: Session, infos: Sequence[StockInfo], now: datetime) -> None:
    for s in infos:
        row = {
            "symbol": s.symbol,
            "name": s.english_name,
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
