"""증권사와 무관한 시세·계좌 형식, 오류 종류, 증권사 연결 규약 (port).

엔진·저장소·Worker는 이 모듈만 안다. 토스 같은 실제 증권사는 adapters/에서 이 형식으로 바꿔 넘긴다.
증권사를 바꾸려면 Broker 규약을 지키는 어댑터 하나만 새로 만들면 된다.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from trading_lab.domain.bars import DailyBar

# --- 오류: 엔진은 이 두 종류로만 판단한다 (project.md 4절 Worker 흐름 7) ---


class BrokerError(Exception):
    """증권사 호출 실패. 일시 장애(429·5xx·네트워크)로 보고 나중에 다시 시도한다."""


class BrokerAccessError(BrokerError):
    """인증·권한·허용 IP 문제. 기다려도 풀리지 않으므로 사람이 확인할 때까지 봇을 멈춘다."""


class RejectReason(StrEnum):
    """증권사가 주문을 거절한 이유 (증권사와 무관). 어댑터가 증권사 오류 코드를 이것으로 바꾼다."""

    OUTSIDE_HOURS = "outside_hours"  # 지금은 이 주문을 받지 않는 시간
    INSUFFICIENT_FUNDS = "insufficient_funds"  # 주문에 쓸 수 있는 돈 부족
    PREREQUISITE = "prerequisite"  # 위험 고지 등 사전 요건
    RESTRICTED = "restricted"  # 종목·계좌 주문 제한
    OTHER = "other"


class OrderRejected(BrokerError):
    """주문이 접수되지 않았다 (보내도 다시 안 되는 거절). 같은 주문을 다시 보내지 않는다."""

    def __init__(self, reason: RejectReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


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


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """1 base = mid_rate quote. 화면에서 바꿔 보기만 한다 (계산·주문은 늘 달러)."""

    base: str  # USD
    quote: str  # KRW
    mid_rate: Decimal  # 매매기준율. 화면 환산에 쓴다
    buy_rate: Decimal | None  # base를 살 때 환율 (참고)
    as_of: datetime


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


class OrderStatus(StrEnum):
    """주문 상태 (증권사와 무관). 어댑터가 증권사 상태 문자열을 이것으로 바꾼다."""

    OPEN = "OPEN"  # 접수됨, 체결 기다림
    PARTIAL = "PARTIAL"  # 일부 체결, 나머지 기다림
    FILLED = "FILLED"
    CANCELED = "CANCELED"  # 취소 (일부 체결됐을 수 있음: filled_quantity)
    REJECTED = "REJECTED"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class AccountOrder:
    """주문 1건 = 1행 (나눠 체결되면 합산)."""

    order_id: str
    symbol: str
    side: str  # BUY | SELL
    status: OrderStatus
    currency: str
    ordered_at: datetime
    order_amount: Decimal | None  # 금액 주문의 금액 (USD)
    filled_quantity: Decimal
    filled_amount: Decimal | None
    quantity: Decimal | None = None  # 수량 주문의 수량 (파는 주문)


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """실제 계좌 읽기 결과. 계좌번호는 담지 않는다."""

    source: str  # 증권사 출처 코드 (화면 이름은 frontend source.ts가 정한다. 예: toss)
    cash_usd: Decimal  # 미수 없는 현금 기준 매수 가능 금액
    cash_krw: Decimal
    holdings: list[Holding]
    orders: list[AccountOrder]  # 진행 중 + 최근 종료 주문, 최신순


# --- 증권사 연결 규약 ---


class Broker(Protocol):
    """시세와 계좌 읽기. 주문을 내는 메서드는 없다 (project.md 3절 원칙 1)."""

    source: str  # 출처 코드. 저장한 봉·계좌에 남기고, 화면 이름은 frontend source.ts가 정한다

    def iter_daily_pages(self, symbol: str, since: date | None = None) -> Iterator[CandlePage]:
        """최신 일봉 페이지부터 과거로. since보다 오래된 봉이 나오면 멈춘다 (수정주가)."""
        ...

    def latest_daily_bar(self, symbol: str) -> DailyBar | None:
        """가장 최근 일봉 1개. 진행 중이면 정규장 전 거래부터 채워진 값일 수 있다."""
        ...

    def instruments(self, symbols: list[str]) -> list[Instrument]: ...

    def quotes(self, symbols: list[str]) -> list[Quote]: ...

    def exchange_rate(self, base: str, quote: str) -> ExchangeRate: ...

    def is_regular_session(self, day: date) -> bool:
        """증권사 기준으로 day가 미국 정규장 거래일인지."""
        ...

    def account_snapshot(self, since: date) -> AccountSnapshot: ...

    def close(self) -> None: ...


# --- 실제 주문 (실거래 R2) ---


@dataclass(frozen=True, slots=True)
class AmountOrder:
    """금액만큼 시장가로 사는 주문 (소수점 매수). 파는 주문은 아직 없다 (사기만)."""

    # 중복 방지 키 (영숫자·-·_ 36자 이내). 같은 키는 idempotency_window 안에서 한 번만 접수된다
    key: str
    symbol: str
    amount: Decimal  # USD, 센트 단위


@dataclass(frozen=True, slots=True)
class SellOrder:
    """수량만큼 시장가로 파는 주문 (소수점 6자리까지). 봇이 실제로 산 만큼만 판다."""

    key: str  # 중복 방지 키 (AmountOrder와 같은 규칙)
    symbol: str
    quantity: Decimal


class Trader(Protocol):
    """실제 주문 규약. 실거래 스위치가 켜졌을 때만 조립 지점이 만든다 (Broker는 읽기만 한다).

    증권사별 규칙(주문 키 형식, 멱등 유효 시간, 접수 시간, 오류 코드)은 어댑터가 이 값으로
    바꿔 넘긴다.
    """

    source: str  # 출처 코드
    idempotency_window: timedelta  # 같은 키로 다시 보내도 새 주문이 되지 않는 시간

    def order_window(self, day: date) -> tuple[datetime, datetime] | None:
        """미국 거래일 day에 금액 주문을 받는 시간 [시작, 끝). 장이 없으면 None."""
        ...

    def available_cash(self) -> Decimal:
        """지금 금액 주문에 쓸 수 있는 달러 (미수 없는 현금 기준)."""
        ...

    def place_amount_buy(self, order: AmountOrder) -> str:
        """주문을 내고 증권사 주문 번호를 돌려준다.

        거절은 OrderRejected, 일시 장애는 BrokerError (같은 키로 다시 보내도 된다).
        """
        ...

    def place_quantity_sell(self, order: SellOrder) -> str:
        """수량만큼 판다. 오류 규칙은 place_amount_buy와 같다."""
        ...

    def get_order(self, order_id: str) -> AccountOrder: ...

    def find_orders(self, symbol: str, day: date) -> list[AccountOrder]:
        """day(한국 날짜)에 낸 그 종목 주문. 결과를 모르는 주문을 찾을 때 쓴다."""
        ...
