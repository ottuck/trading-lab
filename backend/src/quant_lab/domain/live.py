"""실제 주문 규칙 (실거래 R2). 증권사와 무관한 순수 로직이다.

나 카피 봇의 모의 매수를 비율(예: 1/100)만큼 줄여 실제 계좌에서 따라 산다.
판단은 모의와 같은 함수이고, 여기서는 "얼마를, 사람에게 묻고 낼지 바로 낼지"만 정한다.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

CENT = Decimal("0.01")

# 화면에서 고르는 비율 (프리셋). 값은 실제 주문 금액 = 모의 매수 금액 × 비율.
# 비율은 1/100 하나만 쓴다 (2026-10-06 사용자 결정). 1/10 버튼은 2026-10-08에 없앴다.
RATIOS: dict[str, Decimal] = {"1/100": Decimal("0.01")}

# 실제로 사고팔 수 있는 레버리지 ETF (2026-10-06 사용자 결정). 그 밖의 레버리지 상품은 넘긴다.
LEVERAGED_ALLOWED = frozenset({"QLD", "TQQQ"})

MIN_AMOUNT = Decimal("1")  # 이보다 작은 몫은 모아 두었다가 넘으면 함께 산다 (소수점 금액 주문 최소)
SEND_DELAY_MINUTES = 5  # 주문 접수 시간이 열리고 이만큼 뒤에 낸다 (장 시작 직후 가격 흔들림 피하기)


@dataclass(frozen=True, slots=True)
class LiveLimits:
    """실제 주문 안전망. 넘는 주문은 자동으로 내지 않고 사람에게 묻는다."""

    per_order: Decimal = Decimal("20")  # 매달 나눠 사기
    per_month: Decimal = Decimal("50")  # 봇 하나당
    # 계좌 전체(모든 봇)가 한 달에 살 수 있는 상한. 위 한도와 달리 승인해도 넘을 수 없다.
    account_month: Decimal = Decimal("100")


class LiveState(StrEnum):
    """실제 주문 1건의 상태. 지우지 않고 남긴다."""

    WAITING_APPROVAL = "WAITING_APPROVAL"  # 사람이 [승인]을 눌러야 낸다
    APPROVED = "APPROVED"  # 접수 시간이 되면 낸다
    SENDING = "SENDING"  # 보내기 전에 먼저 적어 둔 상태. 결과를 모르면 이 상태로 남는다
    SENT = "SENT"  # 증권사가 받음 (주문 번호 있음), 체결 기다림
    FILLED = "FILLED"
    CANCELED = "CANCELED"  # 증권사에서 취소됨 (일부 체결됐을 수 있음)
    REJECTED = "REJECTED"  # 증권사가 거절
    SKIPPED = "SKIPPED"  # 내지 않음 (거절함·비상 중지·시간 놓침·레버리지·너무 작음)
    UNKNOWN = "UNKNOWN"  # 보냈는지 확인할 수 없음. 사람이 증권사 앱에서 확인해야 한다


OPEN_STATES = {LiveState.WAITING_APPROVAL, LiveState.APPROVED, LiveState.SENDING, LiveState.SENT}


class SkipReason(StrEnum):
    DECLINED = "declined"  # 사람이 "이번엔 안 사기"
    HALTED = "halted"  # 비상 중지 중
    MISSED = "missed"  # 접수 시간 안에 내지 못함 (PC 꺼짐 등)
    NO_SESSION = "no_session"  # 그날 장이 열리지 않음
    LEVERAGED = "leveraged"  # 레버리지 ETF는 실제로 사지 않는다
    # 사기: 2026-10-04 이전 기록만 (지금은 CARRIED로 모아 둔다). 팔기: AI 봇의 일부 팔기가 $1 미만
    TOO_SMALL = "too_small"
    CARRIED = "carried"  # 금액이 작아 모아 둠. 같은 종목 다음 주문에 더해 함께 산다
    NO_FUNDS = "no_funds"  # 보내기 직전 달러가 모자라 넘김 (다음 달에 더하지 않는다)
    NOTHING_HELD = "nothing_held"  # 팔지만 이 봇이 실제로 산 주식이 없음 (켜기 전 모의 보유)
    ACCOUNT_LIMIT = "account_limit"  # 계좌 전체 한 달 상한을 넘어 넘김 (승인해도 넘을 수 없다)


def scaled_amount(budget: Decimal, ratio: Decimal) -> Decimal:
    """실제 주문 금액 = 모의 매수 금액 × 비율, 센트 아래는 버린다 (한도를 넘지 않게)."""
    return (budget * ratio).quantize(CENT, rounding=ROUND_DOWN)


def needs_approval(
    amount: Decimal,
    month_total: Decimal,
    limits: LiveLimits,
    *,
    blocked: bool = False,
) -> bool:
    """한도를 넘는 사기 주문과, 실제 계좌가 봇 기록과 맞지 않는 동안(blocked)의 주문만 묻는다.

    한도 안의 주문은 묻지 않고 바로 낸다 (처음 몇 번 승인받는 단계는 2026-10-08에 없앴다).
    month_total은 이번 달에 이미 내기로 한(승인·보냄·체결) 사기 금액이다.
    """
    over = amount > limits.per_order or month_total + amount > limits.per_month
    return blocked or over


def over_account_limit(amount: Decimal, account_month_total: Decimal, limits: LiveLimits) -> bool:
    """계좌 전체의 이번 달 사기 합계(account_month_total)에 이 주문을 더하면 상한을 넘는지."""
    return account_month_total + amount > limits.account_month


QTY = Decimal("0.000001")  # 소수점 수량 최소 단위 (6자리)


def partial_sell_qty(
    live_qty: Decimal, sim_qty: Decimal, sim_amount: Decimal, close: Decimal
) -> Decimal:
    """AI 봇의 일부 팔기 (마일스톤 4): 모의 보유 중 판 비율만큼 이 봇이 실제로 산 수량에서 판다.

    sim_amount는 모의로 팔 금액(판단일 종가 어림), sim_qty는 그때 모의 보유 수량이다.
    비율을 알 수 없으면(보유·가격 0) 모두 판다. 소수점 6자리 아래는 버린다.
    """
    if sim_qty <= 0 or close <= 0:
        return live_qty
    fraction = min(Decimal(1), sim_amount / (sim_qty * close))
    return (live_qty * fraction).quantize(QTY, rounding=ROUND_DOWN)


def order_key(bot_id: int, symbol: str, signal_date: date, side: str = "BUY") -> str:
    """판단 키(봇·종목·판단일·방향)에서 만든 중복 방지 키. 같은 판단의 주문은 늘 같은 키다."""
    safe = "".join(c if c.isalnum() else "_" for c in symbol)
    suffix = "-S" if side == "SELL" else ""
    return f"ql-{bot_id}-{safe}-{signal_date:%Y%m%d}"[: 36 - len(suffix)] + suffix


def live_allowed(symbol: str, leverage: Decimal | None) -> bool:
    """실제로 사고팔 수 있는 종목인지. 레버리지는 허용한 ETF만."""
    return leverage is None or leverage <= 1 or symbol in LEVERAGED_ALLOWED


QTY_TOLERANCE = Decimal("0.000001")  # 소수점 6자리 반올림 차이


def holding_shortfalls(
    held: dict[str, Decimal], bought: dict[str, Decimal]
) -> dict[str, tuple[Decimal, Decimal]]:
    """실제 계좌 보유가 봇이 실제로 산 수량보다 적은 종목 → (보유, 봇이 산 수량).

    실제 계좌에는 직접 산 주식이 섞일 수 있어 "같은지"가 아니라 "적지 않은지"만 본다.
    봇은 사기만 하므로 적다면 기록이 틀렸거나, 사람이 직접 팔았거나, 계좌에 문제가 있는 것이다.
    """
    return {
        symbol: (held.get(symbol, Decimal(0)), qty)
        for symbol, qty in sorted(bought.items())
        if held.get(symbol, Decimal(0)) + QTY_TOLERANCE < qty
    }


@dataclass(frozen=True, slots=True)
class RealFill:
    """체결된 실제 주문 1건 (체결 수량·금액 기준). month는 거래일의 달 (YYYY-MM)."""

    bot_id: int | None
    symbol: str
    side: str  # BUY | SELL
    qty: Decimal
    amount: Decimal
    month: str


@dataclass(frozen=True)
class RealLedger:
    """봇이 낸 실제 주문의 장부. 달마다 산·판 금액과 확정 손익, 지금 봇이 들고 있는 수량과 원가."""

    bought: dict[str, Decimal] = field(default_factory=dict)
    sold: dict[str, Decimal] = field(default_factory=dict)
    realized: dict[str, Decimal] = field(default_factory=dict)
    held: dict[str, tuple[Decimal, Decimal]] = field(default_factory=dict)  # 종목 → (수량, 원가)


def real_ledger(fills: Sequence[RealFill]) -> RealLedger:
    """체결 순서대로 평균 단가 방식으로 확정 손익을 계산한다 (봇·종목마다 따로).

    판 금액 - 평균 단가 × 판 수량이 확정 손익이다. 수수료는 넣지 않은 어림값이고,
    봇이 낸 주문만 센다 (실제 계좌에 직접 산 주식은 모른다).
    산 것보다 많이 팔았다면 있는 만큼만 센다.
    """
    book: dict[tuple[int | None, str], tuple[Decimal, Decimal]] = {}
    bought: dict[str, Decimal] = {}
    sold: dict[str, Decimal] = {}
    realized: dict[str, Decimal] = {}
    for f in fills:
        key = (f.bot_id, f.symbol)
        qty, cost = book.get(key, (Decimal(0), Decimal(0)))
        if f.side == "SELL":
            sold[f.month] = sold.get(f.month, Decimal(0)) + f.amount
            avg = cost / qty if qty > 0 else Decimal(0)
            take = min(f.qty, qty)
            realized[f.month] = realized.get(f.month, Decimal(0)) + f.amount - avg * take
            book[key] = (qty - take, cost - avg * take)
        else:
            bought[f.month] = bought.get(f.month, Decimal(0)) + f.amount
            book[key] = (qty + f.qty, cost + f.amount)
    held: dict[str, tuple[Decimal, Decimal]] = {}
    for (_, symbol), (qty, cost) in book.items():
        if qty > 0:
            q, c = held.get(symbol, (Decimal(0), Decimal(0)))
            held[symbol] = (q + qty, c + cost)
    return RealLedger(bought, sold, realized, held)
