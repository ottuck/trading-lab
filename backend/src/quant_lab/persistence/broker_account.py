"""실제 증권사 계좌 읽기 결과 저장 (실거래 R1). 1행만 두고 덮어쓴다."""

from datetime import datetime

from sqlalchemy.orm import Session

from quant_lab.domain.broker import AccountOrder, AccountSnapshot
from quant_lab.persistence.models import BrokerAccountRow

ROW_ID = 1
MAX_ORDERS = 20  # 화면에 보여줄 최근 주문 수


def _row(session: Session) -> BrokerAccountRow:
    row = session.get(BrokerAccountRow, ROW_ID, with_for_update=True)
    if row is None:
        row = BrokerAccountRow(id=ROW_ID, holdings=[], orders=[])
        session.add(row)
    return row


def _amount(o: AccountOrder) -> str | None:
    """체결됐으면 체결 금액, 아니면 금액 주문의 금액."""
    amount = o.filled_amount if o.filled_amount else o.order_amount
    return str(amount) if amount is not None else None


def save_snapshot(session: Session, snap: AccountSnapshot, now: datetime) -> None:
    row = _row(session)
    row.source = snap.source
    row.cash_usd = snap.cash_usd
    row.cash_krw = snap.cash_krw
    row.holdings = [
        {
            "symbol": h.symbol,
            "name": h.name,
            "currency": h.currency,
            "qty": str(h.quantity),
            "avg_price": str(h.average_price),
            "last_price": str(h.last_price),
            "value": str(h.market_value),
        }
        for h in snap.holdings
    ]
    row.orders = [
        {
            "symbol": o.symbol,
            "side": o.side,
            "status": o.status,
            "currency": o.currency,
            "ordered_at": o.ordered_at.isoformat(),
            "amount": _amount(o),
            "qty": str(o.filled_quantity),
        }
        for o in snap.orders[:MAX_ORDERS]
    ]
    row.fetched_at = now
    row.error = row.error_at = None


def save_error(session: Session, kind: str, now: datetime) -> None:
    """마지막으로 읽은 값은 그대로 두고 실패만 적는다."""
    row = _row(session)
    row.error = kind
    row.error_at = now
