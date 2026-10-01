# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx>=0.28", "python-dotenv>=1.0"]
# ///
"""토스증권 Open API 읽기 전용 탐색 스크립트 (로드맵 Phase 0).

시세·종목·장 운영 API만 호출한다. 계좌·주문 API는 호출하지 않는다.
출력은 요약값뿐이며 원본 응답은 저장하지 않는다 (토스 데이터 제3자 배포 금지).

사용법:
    uv run scripts/toss_probe.py            # 전체 검사
    uv run scripts/toss_probe.py token stocks daily

필요한 환경변수 (.env 또는 셸): TOSS_CLIENT_ID, TOSS_CLIENT_SECRET
주의: 실행할 때마다 토큰을 새로 발급하므로, 같은 client로 동작 중인 다른 프로세스의 토큰은 무효화된다.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv

BASE_URL = "https://openapi.tossinvest.com"
WATCHLIST = ["VOO", "QQQ", "QLD", "TQQQ", "SOXL", "NVDA", "GLD", "MAGS", "EWY", "EWJ"]
FIRST_SYMBOLS = ["VOO", "QQQ"]
RATE_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")


class Toss:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._http = httpx.Client(base_url=BASE_URL, timeout=15)
        self._client_id = client_id
        self._client_secret = client_secret
        self.token: str | None = None
        self.expires_in: int | None = None
        self.rate_headers: dict[str, dict[str, str]] = {}

    def issue_token(self) -> None:
        resp = self._http.post(
            "/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if resp.status_code != 200:
            raise SystemExit(f"토큰 발급 실패: HTTP {resp.status_code} {resp.text[:300]}")
        body = resp.json()
        self.token = body["access_token"]
        self.expires_in = body.get("expires_in")

    def get(self, path: str, group: str, **params: object) -> httpx.Response:
        assert self.token, "issue_token() 먼저 호출"
        for attempt in range(4):
            resp = self._http.get(
                path, params=params, headers={"Authorization": f"Bearer {self.token}"}
            )
            self.rate_headers[group] = {h: resp.headers.get(h, "-") for h in RATE_HEADERS}
            if resp.status_code != 429:
                return resp
            time.sleep(float(resp.headers.get("Retry-After", 2**attempt)))
        return resp


def error_summary(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        return f"HTTP {resp.status_code} {err.get('code')} {err.get('message')} (requestId={err.get('requestId')})"
    except ValueError:
        return f"HTTP {resp.status_code} {resp.text[:200]}"


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def check_token(t: Toss) -> None:
    section("토큰")
    print(f"발급 성공, expires_in = {t.expires_in}초 ({(t.expires_in or 0) / 3600:.1f}시간)")


def check_stocks(t: Toss) -> None:
    section("종목 정보 /stocks")
    resp = t.get("/api/v1/stocks", "STOCK", symbols=",".join(WATCHLIST))
    if resp.status_code != 200:
        print("실패:", error_summary(resp))
        return
    found = {s["symbol"]: s for s in resp.json()["result"]}
    for sym in WATCHLIST:
        s = found.get(sym)
        if not s:
            print(f"{sym:5} 없음")
            continue
        print(
            f"{sym:5} {s['market']:6} {s['securityType']:11} {s['status']:9} "
            f"{s['currency']} leverage={s.get('leverageFactor')} name={s['englishName']}"
        )


def fetch_all_candles(t: Toss, symbol: str, interval: str, max_pages: int) -> tuple[list[dict], int, bool]:
    candles: list[dict] = []
    before: str | None = None
    pages = 0
    while pages < max_pages:
        params: dict[str, object] = {"symbol": symbol, "interval": interval, "count": 200}
        if before:
            params["before"] = before
        resp = t.get("/api/v1/candles", "MARKET_DATA_CHART", **params)
        pages += 1
        if resp.status_code != 200:
            print(f"  {symbol} {interval} 실패:", error_summary(resp))
            break
        result = resp.json()["result"]
        candles.extend(result["candles"])
        before = result.get("nextBefore")
        if not before or not result["candles"]:
            return candles, pages, True
        time.sleep(0.06)
    return candles, pages, False


def check_daily(t: Toss) -> None:
    section("일봉 전체 이력 /candles 1d")
    for sym in FIRST_SYMBOLS:
        candles, pages, complete = fetch_all_candles(t, sym, "1d", max_pages=80)
        if not candles:
            continue
        ts = sorted(c["timestamp"] for c in candles)
        dupes = len(ts) - len(set(ts))
        print(
            f"{sym}: {len(candles)}개, {pages}페이지, 끝까지={complete}, "
            f"가장 오래된={ts[0]}, 최신={ts[-1]}, 중복 timestamp={dupes}"
        )
        days = [datetime.fromisoformat(x).date() for x in ts]
        gaps = [(a, b) for a, b in zip(days, days[1:]) if (b - a).days > 4]
        print(f"  4일 넘게 빈 구간 {len(gaps)}개: {gaps[:8]}")
        latest = max(candles, key=lambda c: c["timestamp"])
        print(f"  최신 봉 필드 예: { {k: latest[k] for k in ('timestamp', 'openPrice', 'closePrice', 'volume', 'currency')} }")
        raw = t.get("/api/v1/candles", "MARKET_DATA_CHART", symbol=sym, interval="1d", count=1, adjusted="false")
        if raw.status_code == 200 and raw.json()["result"]["candles"]:
            print(f"  adjusted=false 최신 종가: {raw.json()['result']['candles'][0]['closePrice']}")


def check_minute_retention(t: Toss) -> None:
    section("1분봉 보존 기간 /candles 1m")
    sym = FIRST_SYMBOLS[0]
    first = t.get("/api/v1/candles", "MARKET_DATA_CHART", symbol=sym, interval="1m", count=3)
    if first.status_code != 200:
        print("실패:", error_summary(first))
        return
    recent = first.json()["result"]["candles"]
    print(f"{sym} 최근 1분봉 timestamp: {[c['timestamp'] for c in recent]}")
    # before를 과거로 옮겨가며 데이터가 있는 가장 오래된 날을 찾는다 (일 단위 이진 탐색).
    now = datetime.now(UTC)

    def has_data(days_ago: int) -> bool:
        before = (now - timedelta(days=days_ago)).isoformat()
        resp = t.get("/api/v1/candles", "MARKET_DATA_CHART", symbol=sym, interval="1m", count=1, before=before)
        if resp.status_code != 200:
            return False
        c = resp.json()["result"]["candles"]
        if not c:
            return False
        got = datetime.fromisoformat(c[0]["timestamp"])
        return (now - got) <= timedelta(days=days_ago + 7)  # 요청 시점 근처에 봉이 있어야 보존된 것

    lo, hi = 1, 365 * 6
    if has_data(hi):
        print(f"{hi}일 전까지도 1분봉 있음")
        return
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if has_data(mid) else (lo, mid)
        time.sleep(0.06)
    print(f"1분봉은 약 {lo}일 전까지 조회됨 ({(now - timedelta(days=lo)).date()} 무렵)")


def check_calendar(t: Toss) -> None:
    section("미국 장 운영 /market-calendar/US")
    resp = t.get("/api/v1/market-calendar/US", "MARKET_INFO")
    if resp.status_code != 200:
        print("실패:", error_summary(resp))
        return
    for key, day in resp.json()["result"].items():
        if not isinstance(day, dict):
            print(f"{key}: {day}")
            continue
        regular = day.get("regularMarket")
        print(f"{key}: date={day.get('date')} regular={regular}")


def check_latest_daily_finality(t: Toss) -> None:
    section("최신 일봉 스냅샷 (확정 시점 관찰용, 장 마감 직후부터 반복 실행)")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    for sym in FIRST_SYMBOLS:
        resp = t.get("/api/v1/candles", "MARKET_DATA_CHART", symbol=sym, interval="1d", count=2)
        if resp.status_code != 200:
            print(f"{sym} 실패:", error_summary(resp))
            continue
        for c in resp.json()["result"]["candles"]:
            print(f"{now} {sym} {c['timestamp']} O={c['openPrice']} H={c['highPrice']} L={c['lowPrice']} C={c['closePrice']} V={c['volume']}")


def check_adjustment(t: Toss) -> None:
    section("수정주가 (NVDA 2024-06-10 10:1 분할 전후)")
    for adjusted in ("true", "false"):
        resp = t.get(
            "/api/v1/candles", "MARKET_DATA_CHART", symbol="NVDA", interval="1d",
            count=6, before="2024-06-12T00:00:00Z", adjusted=adjusted,
        )
        if resp.status_code != 200:
            print(f"adjusted={adjusted} 실패:", error_summary(resp))
            continue
        rows = [(c["timestamp"][:10], c["closePrice"], c["volume"]) for c in resp.json()["result"]["candles"]]
        print(f"adjusted={adjusted}: {sorted(rows)}")


def check_today_bar(t: Toss) -> None:
    section("진행 중인 일봉 / 1분봉 공백")
    resp = t.get("/api/v1/candles", "MARKET_DATA_CHART", symbol="VOO", interval="1m", count=30)
    if resp.status_code == 200:
        ts = sorted(datetime.fromisoformat(c["timestamp"]) for c in resp.json()["result"]["candles"])
        missing = sum(int((b - a).total_seconds() // 60) - 1 for a, b in zip(ts, ts[1:]))
        zero_vol = sum(1 for c in resp.json()["result"]["candles"] if c["volume"] in ("0", "0.0"))
        print(f"최근 1분봉 30개 구간 {ts[0]} ~ {ts[-1]}: 빠진 분 {missing}개, 거래량 0 봉 {zero_vol}개")


def check_rate_headers(t: Toss) -> None:
    section("Rate limit 헤더 (그룹별 마지막 응답)")
    for group, headers in t.rate_headers.items():
        print(f"{group:20} {headers}")


CHECKS = {
    "token": check_token,
    "stocks": check_stocks,
    "daily": check_daily,
    "minute": check_minute_retention,
    "calendar": check_calendar,
    "finality": check_latest_daily_finality,
    "adjust": check_adjustment,
    "today": check_today_bar,
    "rate": check_rate_headers,
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows 콘솔 한글 깨짐 방지
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client_id = os.environ.get("TOSS_CLIENT_ID")
    client_secret = os.environ.get("TOSS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("TOSS_CLIENT_ID, TOSS_CLIENT_SECRET 환경변수를 설정하세요 (.env.example 참고).")
    names = sys.argv[1:] or list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        raise SystemExit(f"알 수 없는 검사: {unknown}. 가능: {list(CHECKS)}")
    t = Toss(client_id, client_secret)
    t.issue_token()
    for name in names:
        CHECKS[name](t)
    if "rate" not in names:
        check_rate_headers(t)


if __name__ == "__main__":
    main()
