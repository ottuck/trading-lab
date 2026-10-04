"""증권사와 무관한 시세·계좌 형식, 오류 종류, 증권사 연결 규약 (port).

엔진·저장소·Worker는 이 모듈만 안다. 토스 같은 실제 증권사는 adapters/에서 이 형식으로 바꿔 넘긴다.
증권사를 바꾸려면 Broker 규약을 지키는 어댑터 하나만 새로 만들면 된다.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from quant_lab.domain.bars import DailyBar

# --- 오류: 엔진은 이 두 종류로만 판단한다 (project.md 4절 Worker 흐름 7) ---


class BrokerError(Exception):
    """증권사 호출 실패. 일시 장애(429·5xx·네트워크)로 보고 나중에 다시 시도한다."""


class BrokerAccessError(BrokerError):
    """인증·권한·허용 IP 문제. 기다려도 풀리지 않으므로 사람이 확인할 때까지 봇을 멈춘다."""


# --- 시세 ---


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    market: str
    security_type: str
    status: str
    currency: str
    leverage_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    price: Decimal
    quoted_at: datetime  # 마지막 체결 시각 (데이마켓·프리·정규·애프터 모두 포함)


@dataclass(frozen=True, slots=True)
class CandlePage:
    bars: list[DailyBar]  # 거래일 오름차순
    next_before: str | None  # 더 과거 페이지를 받을 커서. 없으면 끝


# --- 계좌 (읽기 전용) ---


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    name: str
    currency: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal
    market_value: Decimal


@dataclass(frozen=True, slots=True)
class AccountOrder:
    """주문 1건 = 1행 (나눠 체결되면 합산)."""

    order_id: str
    symbol: str
    side: str  # BUY | SELL
    status: str  # PENDING, FILLED, CANCELED ...
    currency: str
    ordered_at: datetime
    order_amount: Decimal | None  # 금액 주문의 금액 (USD)
    filled_quantity: Decimal
    filled_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """실제 계좌 읽기 결과. 계좌번호는 담지 않는다."""

    cash_usd: Decimal  # 미수 없는 현금 기준 매수 가능 금액
    cash_krw: Decimal
    holdings: list[Holding]
    orders: list[AccountOrder]  # 진행 중 + 최근 종료 주문, 최신순


# --- 증권사 연결 규약 ---


class Broker(Protocol):
    """시세와 계좌 읽기. 주문을 내는 메서드는 없다 (project.md 3절 원칙 1)."""

    def iter_daily_pages(self, symbol: str, since: date | None = None) -> Iterator[CandlePage]:
        """최신 일봉 페이지부터 과거로. since보다 오래된 봉이 나오면 멈춘다 (수정주가)."""
        ...

    def latest_daily_bar(self, symbol: str) -> DailyBar | None:
        """가장 최근 일봉 1개. 진행 중이면 정규장 전 거래부터 채워진 값일 수 있다."""
        ...

    def instruments(self, symbols: list[str]) -> list[Instrument]: ...

    def quotes(self, symbols: list[str]) -> list[Quote]: ...

    def is_regular_session(self, day: date) -> bool:
        """증권사 기준으로 day가 미국 정규장 거래일인지."""
        ...

    def account_snapshot(self, since: date) -> AccountSnapshot: ...
