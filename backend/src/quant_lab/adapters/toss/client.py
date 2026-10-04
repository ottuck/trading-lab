"""토스증권 Open API 읽기 전용 클라이언트.

- 토큰은 이 클라이언트 하나가 발급·보유한다 (클라이언트당 유효 토큰 1개, docs/tossApi.md).
- 계좌는 읽기만 한다 (실거래 R1). 주문을 내는 API는 구현하지 않는다 (project.md 3절 원칙 1).
"""

import logging
import random
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.broker import (
    AccountOrder,
    AccountSnapshot,
    BrokerAccessError,
    BrokerError,
    CandlePage,
    ExchangeRate,
    Holding,
    Instrument,
    OrderStatus,
    Quote,
)

BASE_URL = "https://openapi.tossinvest.com"
SOURCE = "toss"  # 저장한 봉·계좌의 출처 코드
NEW_YORK = ZoneInfo("America/New_York")
MAX_CANDLES_PER_PAGE = 200
TOKEN_REFRESH_MARGIN = timedelta(hours=1)
MAX_ATTEMPTS = 4

log = logging.getLogger(__name__)


class TossError(BrokerError):
    def __init__(self, status: int, code: str | None, message: str, request_id: str | None):
        super().__init__(f"HTTP {status} {code}: {message} (requestId={request_id})")
        self.status = status
        self.code = code
        self.request_id = request_id


class TossAuthError(TossError, BrokerAccessError):
    """인증 실패. token-revoked가 반복되면 다른 프로세스가 같은 client로 토큰을 발급한 것이다."""


class TossForbiddenError(TossError, BrokerAccessError):
    """허용 IP가 아니거나 권한이 없음. 재시도하지 않는다."""


class TossNetworkError(BrokerError):
    """연결·타임아웃 등 응답을 받지 못한 실패. 일시 장애로 본다."""


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    expires_at: datetime


def _error_from(resp: httpx.Response) -> TossError:
    code: str | None = None
    message = resp.text[:200]
    request_id = resp.headers.get("X-Request-Id")
    try:
        err = resp.json().get("error") or {}
        code = err.get("code")
        message = err.get("message") or message
        request_id = err.get("requestId") or request_id
    except ValueError:
        pass
    if resp.status_code == 401:
        return TossAuthError(resp.status_code, code, message, request_id)
    if resp.status_code == 403:
        return TossForbiddenError(resp.status_code, code, message, request_id)
    return TossError(resp.status_code, code, message, request_id)


def to_daily_bar(symbol: str, raw: Mapping[str, Any]) -> DailyBar:
    # 일봉 timestamp는 미국 현지 자정을 KST로 표현한 값이다 (예: 13:00+09:00).
    ts = datetime.fromisoformat(raw["timestamp"])
    return DailyBar(
        symbol=symbol,
        session_date=ts.astimezone(NEW_YORK).date(),
        open=Decimal(raw["openPrice"]),
        high=Decimal(raw["highPrice"]),
        low=Decimal(raw["lowPrice"]),
        close=Decimal(raw["closePrice"]),
        volume=Decimal(raw["volume"]),
    )


class TossClient:
    source = SOURCE

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.Client | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=15)
        self._now = now
        self._sleep = sleep
        self._token: _Token | None = None
        self._account: int | None = None
        self.last_rate_limit: dict[str, str] = {}

    def close(self) -> None:
        self._http.close()

    # --- 인증 ---

    def _issue_token(self) -> _Token:
        resp = self._send(
            self._http.post,
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if resp.status_code != 200:
            raise _error_from(resp)
        body = resp.json()
        token = _Token(
            value=body["access_token"],
            expires_at=self._now() + timedelta(seconds=int(body["expires_in"])),
        )
        log.info("토스 토큰 발급, 만료 %s", token.expires_at.isoformat())
        return token

    def _bearer(self) -> str:
        if self._token is None or self._now() >= self._token.expires_at - TOKEN_REFRESH_MARGIN:
            self._token = self._issue_token()
        return self._token.value

    # --- 공통 요청 ---

    @staticmethod
    def _send(method: Callable[..., httpx.Response], *args: Any, **kwargs: Any) -> httpx.Response:
        """httpx 오류가 바깥(엔진)으로 새지 않게 증권사 공통 오류로 바꾼다."""
        try:
            return method(*args, **kwargs)
        except httpx.HTTPError as exc:
            raise TossNetworkError(f"토스 연결 실패: {exc!r}") from exc

    def _get(self, path: str, params: Mapping[str, Any], *, account: bool = False) -> Any:
        reissued = False
        for attempt in range(MAX_ATTEMPTS):
            headers = {"Authorization": f"Bearer {self._bearer()}"}
            if account:
                headers["X-Tossinvest-Account"] = str(self._account_seq())
            resp = self._send(self._http.get, path, params=params, headers=headers)
            self.last_rate_limit = {
                k: v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit")
            }
            if resp.status_code == 200:
                return resp.json()["result"]

            err = _error_from(resp)
            if isinstance(err, TossAuthError) and not reissued:
                # 만료·무효화된 토큰은 한 번만 재발급한다. 또 실패하면 토큰 경합으로 보고 멈춘다.
                log.warning("토스 인증 실패 %s, 토큰 재발급", err.code)
                self._token = None
                reissued = True
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == MAX_ATTEMPTS - 1:
                    raise err
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2**attempt
                self._sleep(delay + random.uniform(0, 0.3))
                continue
            raise err
        raise RuntimeError("unreachable")

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        """주문용 POST (계좌 헤더). 다시 보내지 않는다: 같은 주문 키로 다시 보낼지는 엔진이 정한다.

        토큰 만료로 인한 401만 한 번 재발급해 다시 보낸다 (요청이 처리되기 전에 거절된 것이다).
        """
        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {self._bearer()}",
                "X-Tossinvest-Account": str(self._account_seq()),
            }
            resp = self._send(self._http.post, path, json=body, headers=headers)
            if resp.status_code == 200:
                return resp.json()["result"]
            err = _error_from(resp)
            if isinstance(err, TossAuthError) and attempt == 0:
                self._token = None
                continue
            raise err
        raise RuntimeError("unreachable")

    # --- 시세·종목 ---

    def instruments(self, symbols: list[str]) -> list[Instrument]:
        result = self._get("/api/v1/stocks", {"symbols": ",".join(symbols)})
        return [
            Instrument(
                symbol=s["symbol"],
                name=s["englishName"],
                market=s["market"],
                security_type=s["securityType"],
                status=s["status"],
                currency=s["currency"],
                leverage_factor=(
                    Decimal(s["leverageFactor"]) if s.get("leverageFactor") is not None else None
                ),
            )
            for s in result
        ]

    def daily_candles(
        self, symbol: str, *, before: str | None = None, count: int = MAX_CANDLES_PER_PAGE
    ) -> CandlePage:
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": "1d",
            "count": count,
            "adjusted": "true",
        }
        if before:
            params["before"] = before
        result = self._get("/api/v1/candles", params)
        bars = [to_daily_bar(symbol, c) for c in result["candles"]]
        bars.sort(key=lambda b: b.session_date)
        return CandlePage(bars=bars, next_before=result.get("nextBefore"))

    def iter_daily_pages(self, symbol: str, since: date | None = None) -> Iterator[CandlePage]:
        """최신 페이지부터 과거로. since보다 오래된 봉이 나오면 멈춘다."""
        before: str | None = None
        while True:
            page = self.daily_candles(symbol, before=before)
            yield page
            if not page.next_before or not page.bars:
                return
            if since is not None and page.bars[0].session_date <= since:
                return
            before = page.next_before

    def quotes(self, symbols: list[str]) -> list[Quote]:
        """현재가. 응답은 symbol·timestamp·lastPrice뿐이다 (tossApi.md 7절)."""
        result = self._get("/api/v1/prices", {"symbols": ",".join(symbols)})
        return [
            Quote(
                symbol=p["symbol"],
                price=Decimal(p["lastPrice"]),
                quoted_at=datetime.fromisoformat(p["timestamp"]),
            )
            for p in result
            if p.get("lastPrice") is not None
        ]

    def exchange_rate(self, base: str, quote: str) -> ExchangeRate:
        """참고용 표시 환율 (1분마다 바뀜). rate는 살 때 환율, midRate는 매매기준율."""
        result = self._get("/api/v1/exchange-rate", {"baseCurrency": base, "quoteCurrency": quote})
        return ExchangeRate(
            base=base,
            quote=quote,
            mid_rate=Decimal(result["midRate"]),
            buy_rate=_decimal_or_none(result.get("rate")),
            as_of=datetime.fromisoformat(result["validFrom"]),
        )

    def latest_daily_bar(self, symbol: str) -> DailyBar | None:
        bars = self.daily_candles(symbol, count=1).bars
        return bars[-1] if bars else None

    def us_market_calendar(self, day: date | None = None) -> dict[str, Any]:
        params = {"date": day.isoformat()} if day else {}
        result: dict[str, Any] = self._get("/api/v1/market-calendar/US", params)
        return result

    def is_regular_session(self, day: date) -> bool:
        today = self.us_market_calendar(day)["today"]
        return str(today.get("date")) == day.isoformat() and today.get("regularMarket") is not None

    # --- 계좌 (읽기 전용) ---

    def _account_seq(self) -> int:
        """계좌 헤더 값. 종합매매 계좌가 하나라 첫 계좌를 쓴다 (tossApi.md 9절)."""
        if self._account is None:
            accounts = self._get("/api/v1/accounts", {})
            if not accounts:
                raise TossError(404, "no-account", "토스 계좌가 없습니다", None)
            self._account = int(accounts[0]["accountSeq"])
        return self._account

    def buying_power(self, currency: str) -> Decimal:
        result = self._get("/api/v1/buying-power", {"currency": currency}, account=True)
        return Decimal(result["cashBuyingPower"])

    def holdings(self) -> list[Holding]:
        result = self._get("/api/v1/holdings", {}, account=True)
        return [
            Holding(
                symbol=h["symbol"],
                name=h["name"],
                currency=h["currency"],
                quantity=Decimal(h["quantity"]),
                average_price=Decimal(h["averagePurchasePrice"]),
                last_price=Decimal(h["lastPrice"]),
                market_value=Decimal(h["marketValue"]["amount"]),
            )
            for h in result["items"]
        ]

    def orders(self, status: str, since: date, max_pages: int = 5) -> list[AccountOrder]:
        """since(KST 주문일) 이후 주문. OPEN은 한 번에 전부, CLOSED는 100건씩 이어서 읽는다."""
        params: dict[str, Any] = {"status": status, "from": since.isoformat(), "limit": 100}
        out: list[AccountOrder] = []
        for _ in range(max_pages):
            page = self._get("/api/v1/orders", params, account=True)
            out += [_to_order(o) for o in page["orders"]]
            if status == "OPEN" or not page.get("hasNext") or not page.get("nextCursor"):
                break
            params["cursor"] = page["nextCursor"]
        return out

    def account_snapshot(self, since: date) -> AccountSnapshot:
        orders = self.orders("OPEN", since) + self.orders("CLOSED", since)
        orders.sort(key=lambda o: o.ordered_at, reverse=True)
        return AccountSnapshot(
            source=SOURCE,
            cash_usd=self.buying_power("USD"),
            cash_krw=self.buying_power("KRW"),
            holdings=self.holdings(),
            orders=orders,
        )


def _decimal_or_none(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


# 토스 주문 상태 → 증권사 무관 상태. 정정·취소 거부 행은 원주문이 따로 있어 거절로 본다.
_STATUS = {
    "PENDING": OrderStatus.OPEN,
    "PENDING_CANCEL": OrderStatus.OPEN,
    "PENDING_REPLACE": OrderStatus.OPEN,
    "PARTIAL_FILLED": OrderStatus.PARTIAL,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "REPLACED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "CANCEL_REJECTED": OrderStatus.REJECTED,
    "REPLACE_REJECTED": OrderStatus.REJECTED,
}


def _to_order(raw: Mapping[str, Any]) -> AccountOrder:
    execution = raw.get("execution") or {}
    return AccountOrder(
        order_id=str(raw["orderId"]),
        symbol=raw["symbol"],
        side=raw["side"],
        status=_STATUS.get(raw["status"], OrderStatus.OTHER),
        currency=raw["currency"],
        ordered_at=datetime.fromisoformat(raw["orderedAt"]),
        order_amount=_decimal_or_none(raw.get("orderAmount")),
        filled_quantity=Decimal(execution.get("filledQuantity") or "0"),
        filled_amount=_decimal_or_none(execution.get("filledAmount")),
    )
