"""실제 주문 규칙 (실거래 R2). 증권사와 무관한 순수 로직이다.

나 카피 봇의 모의 매수를 비율(예: 1/100)만큼 줄여 실제 계좌에서 따라 산다.
판단은 모의와 같은 함수이고, 여기서는 "얼마를, 사람에게 묻고 낼지 바로 낼지"만 정한다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

CENT = Decimal("0.01")

# 화면에서 고르는 비율 (프리셋). 값은 실제 주문 금액 = 모의 매수 금액 × 비율
RATIOS: dict[str, Decimal] = {"1/100": Decimal("0.01"), "1/10": Decimal("0.1")}

AUTO_AFTER = 3  # 승인한 주문이 이만큼 연속으로 문제없이 체결되면 그다음부터 자동으로 낸다
MIN_AMOUNT = Decimal("1")  # 이보다 작은 몫은 모아 두었다가 넘으면 함께 산다 (소수점 금액 주문 최소)
SEND_DELAY_MINUTES = 5  # 주문 접수 시간이 열리고 이만큼 뒤에 낸다 (장 시작 직후 가격 흔들림 피하기)


@dataclass(frozen=True, slots=True)
class LiveLimits:
    """실제 주문 안전망. 넘는 주문은 자동으로 내지 않고 사람에게 묻는다."""

    per_order: Decimal = Decimal("20")
    per_month: Decimal = Decimal("50")


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
    TOO_SMALL = "too_small"  # 2026-10-04 이전 기록만 (지금은 CARRIED로 모아 둔다)
    CARRIED = "carried"  # 금액이 작아 모아 둠. 같은 종목 다음 주문에 더해 함께 산다
    NO_FUNDS = "no_funds"  # 보내기 직전 달러가 모자라 넘김 (다음 달에 더하지 않는다)


def scaled_amount(budget: Decimal, ratio: Decimal) -> Decimal:
    """실제 주문 금액 = 모의 매수 금액 × 비율, 센트 아래는 버린다 (한도를 넘지 않게)."""
    return (budget * ratio).quantize(CENT, rounding=ROUND_DOWN)


def needs_approval(amount: Decimal, month_total: Decimal, streak: int, limits: LiveLimits) -> bool:
    """처음 AUTO_AFTER번은 늘 묻고, 한도를 넘는 주문은 자동 단계에서도 묻는다.

    month_total은 이번 달에 이미 내기로 한(승인·보냄·체결) 금액이다.
    """
    over = amount > limits.per_order or month_total + amount > limits.per_month
    return streak < AUTO_AFTER or over


def order_key(bot_id: int, symbol: str, signal_date: date) -> str:
    """판단 키(봇·종목·판단일)에서 만든 중복 방지 키. 같은 판단의 주문은 늘 같은 키다."""
    safe = "".join(c if c.isalnum() else "_" for c in symbol)
    return f"ql-{bot_id}-{safe}-{signal_date:%Y%m%d}"[:36]


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
