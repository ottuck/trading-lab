from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from trading_lab.domain.bars import DailyBar
from trading_lab.persistence.models import DailyBarRow


def _to_domain(row: DailyBarRow) -> DailyBar:
    return DailyBar(
        symbol=row.symbol,
        session_date=row.session_date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
    )


def upsert_daily_bars(
    session: Session, bars: Sequence[DailyBar], source: str, fetched_at: datetime
) -> None:
    if not bars:
        return
    rows = [
        {
            "symbol": b.symbol,
            "session_date": b.session_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "source": source,
            "fetched_at": fetched_at,
        }
        for b in bars
    ]
    stmt = insert(DailyBarRow)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DailyBarRow.symbol, DailyBarRow.session_date],
        set_={
            c: stmt.excluded[c]
            for c in ("open", "high", "low", "close", "volume", "source", "fetched_at")
        },
    )
    # PostgreSQL 파라미터 한도를 넘지 않게 나눠 넣는다.
    for i in range(0, len(rows), 1000):
        session.execute(stmt, rows[i : i + 1000])


def delete_daily_bars(session: Session, symbol: str) -> None:
    session.execute(delete(DailyBarRow).where(DailyBarRow.symbol == symbol))


def load_daily_bars(
    session: Session, symbol: str, start: date | None = None, end: date | None = None
) -> list[DailyBar]:
    stmt = select(DailyBarRow).where(DailyBarRow.symbol == symbol)
    if start:
        stmt = stmt.where(DailyBarRow.session_date >= start)
    if end:
        stmt = stmt.where(DailyBarRow.session_date <= end)
    stmt = stmt.order_by(DailyBarRow.session_date)
    return [_to_domain(r) for r in session.scalars(stmt)]


def latest_session_date(session: Session, symbol: str) -> date | None:
    return session.scalar(
        select(func.max(DailyBarRow.session_date)).where(DailyBarRow.symbol == symbol)
    )
