"""토스 실제 주문 어댑터 (실거래 R2). domain/broker.py의 Trader 규약을 토스 API로 구현한다.

토스만의 규칙은 여기서 끝난다: clientOrderId 형식, 멱등 키 10분, 금액 주문 접수 시간
(정규장 시작 ~ 마감 1시간 전), 주문 조회에 clientOrderId가 없음, 오류 코드 (docs/tossApi.md 5·9절).
"""

from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from trading_lab.adapters.toss.client import SOURCE, TossClient, TossError, _to_order
from trading_lab.domain.broker import (
    AccountOrder,
    AmountOrder,
    BrokerAccessError,
    OrderRejected,
    RejectReason,
    SellOrder,
)

AMOUNT_ORDER_CUTOFF = timedelta(hours=1)  # 금액 주문은 정규장 마감 1시간 전까지만 받는다

# 토스 422 오류 코드 → 거절 이유. 여기 없는 4xx는 OTHER로 본다.
_REJECT = {
    "amount-order-outside-regular-hours": RejectReason.OUTSIDE_HOURS,
    "fractional-quantity-outside-regular-hours": RejectReason.OUTSIDE_HOURS,
    "order-hours-closed": RejectReason.OUTSIDE_HOURS,
    "insufficient-buying-power": RejectReason.INSUFFICIENT_FUNDS,
    "max-order-amount-exceeded": RejectReason.INSUFFICIENT_FUNDS,
    "prerequisite-required": RejectReason.PREREQUISITE,
    "stock-restricted": RejectReason.RESTRICTED,
    "account-restricted": RejectReason.RESTRICTED,
    "market-not-supported-for-stock": RejectReason.RESTRICTED,
}
# 처리 중이거나 잠시 뒤 될 수 있는 응답. 같은 키로 다시 보내도 된다.
_RETRYABLE = {"request-in-progress"}


class TossTrader:
    source = SOURCE
    idempotency_window = timedelta(minutes=10)

    def __init__(self, client: TossClient) -> None:
        self.client = client

    def order_window(self, day: date) -> tuple[datetime, datetime] | None:
        cal = self.client.us_market_calendar(day)
        for key in ("today", "previousBusinessDay", "nextBusinessDay"):
            entry = cal.get(key) or {}
            if str(entry.get("date")) != day.isoformat():
                continue
            regular = entry.get("regularMarket")
            if not regular:
                return None
            start = datetime.fromisoformat(regular["startTime"])
            end = datetime.fromisoformat(regular["endTime"]) - AMOUNT_ORDER_CUTOFF
            return start, end
        return None

    def available_cash(self) -> Decimal:
        return self.client.buying_power("USD")

    def place_amount_buy(self, order: AmountOrder) -> str:
        return self._place(
            {
                "clientOrderId": order.key,
                "symbol": order.symbol,
                "side": "BUY",
                "orderType": "MARKET",
                "orderAmount": f"{order.amount:.2f}",
            }
        )

    def place_quantity_sell(self, order: SellOrder) -> str:
        """소수점 수량 시장가 매도 (US, 6자리까지, 정규장 시작 ~ 마감 1시간 전)."""
        qty = order.quantity.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        return self._place(
            {
                "clientOrderId": order.key,
                "symbol": order.symbol,
                "side": "SELL",
                "orderType": "MARKET",
                "quantity": format(qty.normalize(), "f"),
            }
        )

    def _place(self, body: dict[str, str]) -> str:
        try:
            result = self.client._post("/api/v1/orders", body)
        except BrokerAccessError:
            raise
        except TossError as exc:
            if exc.status >= 500 or exc.status == 429 or exc.code in _RETRYABLE:
                raise
            reason = _REJECT.get(exc.code or "", RejectReason.OTHER)
            raise OrderRejected(reason, str(exc)) from exc
        return str(result["orderId"])

    def get_order(self, order_id: str) -> AccountOrder:
        return _to_order(self.client._get(f"/api/v1/orders/{order_id}", {}, account=True))

    def find_orders(self, symbol: str, day: date) -> list[AccountOrder]:
        found: list[AccountOrder] = []
        for status in ("OPEN", "CLOSED"):
            params = {
                "status": status,
                "symbol": symbol,
                "from": day.isoformat(),
                "to": day.isoformat(),
            }
            page = self.client._get("/api/v1/orders", {**params, "limit": 100}, account=True)
            found += [_to_order(o) for o in page["orders"]]
        return found
