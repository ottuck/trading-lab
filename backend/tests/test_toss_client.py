from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from quant_lab.adapters.toss.client import (
    BASE_URL,
    TossAuthError,
    TossClient,
    TossForbiddenError,
    to_daily_bar,
)

TOKEN_URL = f"{BASE_URL}/oauth2/token"
CANDLES_URL = f"{BASE_URL}/api/v1/candles"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def candle(ts: str, close: str = "100") -> dict[str, str]:
    return {
        "timestamp": ts,
        "openPrice": close,
        "highPrice": close,
        "lowPrice": close,
        "closePrice": close,
        "volume": "10",
        "currency": "USD",
    }


def token_response(n: int = 1) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": f"t{n}", "token_type": "Bearer", "expires_in": 86399}
    )


def candles_response(*items: dict[str, str], next_before: str | None = None) -> httpx.Response:
    return httpx.Response(200, json={"result": {"candles": list(items), "nextBefore": next_before}})


def error_response(status: int, code: str, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"requestId": "r1", "code": code, "message": code}},
        headers=headers,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def client(clock: Clock, sleeps: list[float]) -> Iterator[TossClient]:
    c = TossClient(
        "id", "secret", http=httpx.Client(base_url=BASE_URL), now=clock, sleep=sleeps.append
    )
    yield c
    c.close()


def test_daily_timestamp_maps_to_new_york_session_date() -> None:
    summer = to_daily_bar("QQQ", candle("2026-09-30T13:00:00.000+09:00"))
    winter = to_daily_bar("QQQ", candle("2002-11-25T14:00:00.000+09:00"))
    assert summer.session_date == date(2026, 9, 30)
    assert winter.session_date == date(2002, 11, 25)
    assert summer.close == Decimal("100")


@respx.mock
def test_token_is_reused_until_refresh_margin(client: TossClient, clock: Clock) -> None:
    token = respx.post(TOKEN_URL).mock(side_effect=[token_response(1), token_response(2)])
    candles = respx.get(CANDLES_URL).mock(return_value=candles_response())

    client.daily_candles("QQQ")
    clock.now += timedelta(hours=22)
    client.daily_candles("QQQ")
    assert token.call_count == 1

    clock.now += timedelta(hours=1, minutes=30)  # 만료 1시간 전 안쪽
    client.daily_candles("QQQ")
    assert token.call_count == 2
    assert candles.calls[-1].request.headers["Authorization"] == "Bearer t2"


@respx.mock
def test_repeated_revocation_raises(client: TossClient) -> None:
    respx.post(TOKEN_URL).mock(side_effect=[token_response(1), token_response(2)])
    respx.get(CANDLES_URL).mock(return_value=error_response(401, "token-revoked"))
    with pytest.raises(TossAuthError) as exc:
        client.daily_candles("QQQ")
    assert exc.value.code == "token-revoked"


@respx.mock
def test_rate_limit_waits_retry_after(client: TossClient, sleeps: list[float]) -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.get(CANDLES_URL).mock(
        side_effect=[
            error_response(429, "rate-limit-exceeded", {"Retry-After": "2"}),
            candles_response(),
        ]
    )
    client.daily_candles("QQQ")
    assert len(sleeps) == 1
    assert 2 <= sleeps[0] < 2.5


@respx.mock
def test_forbidden_is_not_retried(client: TossClient) -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    route = respx.get(CANDLES_URL).mock(return_value=error_response(403, "edge-blocked"))
    with pytest.raises(TossForbiddenError):
        client.daily_candles("QQQ")
    assert route.call_count == 1


@respx.mock
def test_pagination_stops_at_since(client: TossClient) -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    route = respx.get(CANDLES_URL).mock(
        side_effect=[
            candles_response(
                candle("2026-10-01T13:00:00+09:00"),
                candle("2026-09-30T13:00:00+09:00"),
                next_before="2026-09-29T13:00:00+09:00",
            ),
            candles_response(
                candle("2026-09-29T13:00:00+09:00"),
                candle("2026-09-28T13:00:00+09:00"),
                next_before="2026-09-25T13:00:00+09:00",
            ),
        ]
    )
    pages = list(client.iter_daily_pages("QQQ", since=date(2026, 9, 29)))
    assert route.call_count == 2
    assert route.calls[1].request.url.params["before"] == "2026-09-29T13:00:00+09:00"
    # 각 페이지는 거래일 오름차순
    assert [b.session_date.day for b in pages[0].bars] == [30, 1]


def test_account_snapshot_reads_with_account_header(client: TossClient) -> None:
    def order(order_id: str, at: str, status: str = "FILLED") -> dict[str, object]:
        return {
            "orderId": order_id,
            "symbol": "VOO",
            "side": "BUY",
            "status": status,
            "currency": "USD",
            "orderedAt": at,
            "orderAmount": "3.5",
            "execution": {"filledQuantity": "0.005", "filledAmount": "3.49"},
        }

    def orders(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        page: dict[str, object]
        if params["status"] == "OPEN":
            page = {"orders": [order("o3", "2026-10-03T23:00:00+09:00", "PENDING")]}
        elif "cursor" not in params:
            page = {
                "orders": [order("o1", "2026-09-01T23:00:00+09:00")],
                "hasNext": True,
                "nextCursor": "c1",
            }
        else:
            page = {"orders": [order("o2", "2026-09-15T23:00:00+09:00")], "hasNext": False}
        return httpx.Response(200, json={"result": {"nextCursor": None, **page}})

    with respx.mock(assert_all_called=True) as mock:
        mock.post(TOKEN_URL).mock(return_value=token_response())
        mock.get(f"{BASE_URL}/api/v1/accounts").mock(
            return_value=httpx.Response(200, json={"result": [{"accountSeq": 7}]})
        )
        cash = {"USD": "12.5", "KRW": "10000"}
        power = mock.get(f"{BASE_URL}/api/v1/buying-power").mock(
            side_effect=lambda r: httpx.Response(
                200, json={"result": {"cashBuyingPower": cash[r.url.params["currency"]]}}
            )
        )
        mock.get(f"{BASE_URL}/api/v1/holdings").mock(
            return_value=httpx.Response(200, json={"result": {"items": []}})
        )
        mock.get(f"{BASE_URL}/api/v1/orders").mock(side_effect=orders)
        snap = client.account_snapshot(date(2026, 9, 1))
        # 계좌 목록은 한 번만 읽고, 계좌 API에는 계좌 헤더를 붙인다.
        assert mock.calls.call_count == 1 + 1 + 3 + 2 + 1
        assert power.calls[0].request.headers["X-Tossinvest-Account"] == "7"

    assert (snap.cash_usd, snap.cash_krw) == (Decimal("12.5"), Decimal("10000"))
    # 진행 중 + 종료 주문을 이어서 읽고 최신순으로 둔다.
    assert [o.order_id for o in snap.orders] == ["o3", "o2", "o1"]
    assert snap.orders[1].filled_amount == Decimal("3.49")
