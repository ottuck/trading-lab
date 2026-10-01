"""토스증권 Open API 읽기 전용 클라이언트.

- 토큰은 이 클라이언트 하나가 발급·보유한다 (클라이언트당 유효 토큰 1개, docs/tossApi.md).
- 계좌·주문 API는 구현하지 않는다 (project.md 3절 원칙 1).
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

BASE_URL = "https://openapi.tossinvest.com"
NEW_YORK = ZoneInfo("America/New_York")
MAX_CANDLES_PER_PAGE = 200
TOKEN_REFRESH_MARGIN = timedelta(hours=1)
MAX_ATTEMPTS = 4

log = logging.getLogger(__name__)


class TossError(Exception):
    def __init__(self, status: int, code: str | None, message: str, request_id: str | None):
        super().__init__(f"HTTP {status} {code}: {message} (requestId={request_id})")
        self.status = status
        self.code = code
        self.request_id = request_id


class TossAuthError(TossError):
    """인증 실패. token-revoked가 반복되면 다른 프로세스가 같은 client로 토큰을 발급한 것이다."""


class TossForbiddenError(TossError):
    """허용 IP가 아니거나 권한이 없음. 재시도하지 않는다."""


@dataclass(frozen=True, slots=True)
class StockInfo:
    symbol: str
    english_name: str
    market: str
    security_type: str
    status: str
    currency: str
    leverage_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class CandlePage:
    bars: list[DailyBar]  # 거래일 오름차순
    next_before: str | None


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
        self.last_rate_limit: dict[str, str] = {}

    def close(self) -> None:
        self._http.close()

    # --- 인증 ---

    def _issue_token(self) -> _Token:
        resp = self._http.post(
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

    def _get(self, path: str, params: Mapping[str, Any]) -> Any:
        reissued = False
        for attempt in range(MAX_ATTEMPTS):
            resp = self._http.get(
                path, params=params, headers={"Authorization": f"Bearer {self._bearer()}"}
            )
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

    # --- 시세·종목 ---

    def stocks(self, symbols: list[str]) -> list[StockInfo]:
        result = self._get("/api/v1/stocks", {"symbols": ",".join(symbols)})
        return [
            StockInfo(
                symbol=s["symbol"],
                english_name=s["englishName"],
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

    def us_market_calendar(self, day: date | None = None) -> dict[str, Any]:
        params = {"date": day.isoformat()} if day else {}
        result: dict[str, Any] = self._get("/api/v1/market-calendar/US", params)
        return result
