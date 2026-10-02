"""규칙 전략. 완료된 봉의 이력만 받아 '보유할지'를 판단한다.

전략은 주문 수량·가격을 정하지 않는다. 수량은 위험 규칙, 체결은 모의 브로커가 정한다.
모으기 전략(매달 입금하고 사 모으는 전략)은 '얼마만큼 살지'를 Spend로 알려 준다.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import ClassVar, Protocol

from quant_lab.domain.bars import DailyBar


class Spend(StrEnum):
    """모으기 전략이 이번 판단에 쓸 돈. 보통 전략(전부 사거나 전부 팔기)은 None을 쓴다."""

    DEPOSIT = "DEPOSIT"  # 입금일에 모아 둔 돈(reserve)을 뺀 현금으로 산다 (그달 입금 + 잔돈)
    ALL = "ALL"  # 모아 둔 돈까지 현금을 모두 산다
    NONE = "NONE"  # 사지 않는다. 오늘 들어온 돈은 모아 둔 돈이 된다


@dataclass(frozen=True, slots=True)
class Signal:
    """long=True면 보유, False면 미보유가 목표. reason은 화면·로그에 그대로 보여준다."""

    long: bool
    reason: str
    indicators: dict[str, Decimal] = field(default_factory=dict)
    spend: Spend | None = None


@dataclass(frozen=True, slots=True)
class DepositPlan:
    """매달 day일(휴장이면 그 뒤 첫 판단일)에 amount달러를 넣는다. 한 달에 한 번."""

    amount: Decimal
    day: int

    def due(self, session_date: date, last_month: str | None) -> bool:
        return session_date.day >= self.day and month_key(session_date) != last_month


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def deposit_plan(strategy: object) -> DepositPlan | None:
    """정기 입금을 하는 전략이면 그 계획, 아니면 None."""
    plan = getattr(strategy, "deposit_plan", None)
    return plan if isinstance(plan, DepositPlan) else None


class Strategy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def params(self) -> dict[str, int]: ...

    @property
    def warmup(self) -> int:
        """판단에 필요한 최소 봉 수."""
        ...

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        """history의 마지막 봉까지 보고 판단한다. 봉이 부족하면 None."""
        ...


def _sma(bars: Sequence[DailyBar], n: int) -> Decimal:
    return sum((b.close for b in bars[-n:]), Decimal(0)) / n


@dataclass(frozen=True)
class SmaCross:
    """빠른 이동평균이 느린 이동평균보다 위면 보유, 아래면 미보유."""

    fast: int = 50
    slow: int = 200
    name: ClassVar[str] = "sma_cross"

    def __post_init__(self) -> None:
        if not 0 < self.fast < self.slow:
            raise ValueError("0 < fast < slow 이어야 합니다")

    @property
    def params(self) -> dict[str, int]:
        return {"fast": self.fast, "slow": self.slow}

    @property
    def warmup(self) -> int:
        return self.slow

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        if len(history) < self.warmup:
            return None
        fast, slow = _sma(history, self.fast), _sma(history, self.slow)
        indicators = {f"sma{self.fast}": fast, f"sma{self.slow}": slow}
        if fast > slow:
            reason = f"SMA{self.fast} {fast:.2f} > SMA{self.slow} {slow:.2f}"
            return Signal(True, reason, indicators)
        reason = f"SMA{self.fast} {fast:.2f} <= SMA{self.slow} {slow:.2f}"
        return Signal(False, reason, indicators)


@dataclass(frozen=True)
class DonchianBreakout:
    """종가가 직전 entry일 최고가를 넘으면 진입, 직전 exit일 최저가 아래로 내려가면 청산."""

    entry: int = 55
    exit: int = 20
    name: ClassVar[str] = "donchian"

    def __post_init__(self) -> None:
        if self.entry <= 0 or self.exit <= 0:
            raise ValueError("entry, exit는 양수여야 합니다")

    @property
    def params(self) -> dict[str, int]:
        return {"entry": self.entry, "exit": self.exit}

    @property
    def warmup(self) -> int:
        return max(self.entry, self.exit) + 1

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        if len(history) < self.warmup:
            return None
        today = history[-1]
        upper = max(b.high for b in history[-self.entry - 1 : -1])
        lower = min(b.low for b in history[-self.exit - 1 : -1])
        indicators = {f"high{self.entry}": upper, f"low{self.exit}": lower}
        if not holding and today.close > upper:
            return Signal(True, f"종가 {today.close} > {self.entry}일 최고가 {upper}", indicators)
        if holding and today.close < lower:
            return Signal(False, f"종가 {today.close} < {self.exit}일 최저가 {lower}", indicators)
        state = "보유 유지" if holding else "관망"
        return Signal(
            holding,
            f"{state}: {self.exit}일 최저 {lower} ~ {self.entry}일 최고 {upper}",
            indicators,
        )


@dataclass(frozen=True)
class TrendFilter:
    """Faber의 추세 필터: 종가가 장기 이동평균 위면 보유, 아래면 현금."""

    sma: int = 200
    name: ClassVar[str] = "trend_filter"

    def __post_init__(self) -> None:
        if self.sma <= 1:
            raise ValueError("sma는 2 이상이어야 합니다")

    @property
    def params(self) -> dict[str, int]:
        return {"sma": self.sma}

    @property
    def warmup(self) -> int:
        return self.sma

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        if len(history) < self.warmup:
            return None
        close, avg = history[-1].close, _sma(history, self.sma)
        indicators = {f"sma{self.sma}": avg}
        if close > avg:
            return Signal(True, f"종가 {close} > SMA{self.sma} {avg:.2f}", indicators)
        return Signal(False, f"종가 {close} <= SMA{self.sma} {avg:.2f}", indicators)


# RSI는 Wilder 평활을 쓴다.
# 판단일까지의 고정 길이 구간으로 계산해 백테스트와 DRY RUN이 같은 값을 얻는다.
RSI_LOOKBACK = 100


def _rsi(bars: Sequence[DailyBar], n: int) -> Decimal:
    closes = [b.close for b in bars[-(RSI_LOOKBACK + 1) :]]
    changes = [b - a for a, b in pairwise(closes)]
    gain = sum((max(c, Decimal(0)) for c in changes[:n]), Decimal(0)) / n
    loss = sum((max(-c, Decimal(0)) for c in changes[:n]), Decimal(0)) / n
    for c in changes[n:]:
        gain = (gain * (n - 1) + max(c, Decimal(0))) / n
        loss = (loss * (n - 1) + max(-c, Decimal(0))) / n
    if loss == 0:
        return Decimal(100)
    return 100 - 100 / (1 + gain / loss)


@dataclass(frozen=True)
class ConnorsRsi2:
    """Connors RSI(2) 눌림목: 장기 추세 위에서 RSI가 과매도면 매수, 단기 이동평균을 넘으면 매도."""

    rsi: int = 2
    entry: int = 10
    exit_sma: int = 5
    trend: int = 200
    name: ClassVar[str] = "rsi2"

    @property
    def params(self) -> dict[str, int]:
        return {
            "rsi": self.rsi,
            "entry": self.entry,
            "exit_sma": self.exit_sma,
            "trend": self.trend,
        }

    @property
    def warmup(self) -> int:
        return max(self.trend, RSI_LOOKBACK + 1)

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        if len(history) < self.warmup:
            return None
        close = history[-1].close
        rsi, trend, exit_avg = (
            _rsi(history, self.rsi),
            _sma(history, self.trend),
            _sma(history, self.exit_sma),
        )
        indicators = {
            f"rsi{self.rsi}": rsi,
            f"sma{self.trend}": trend,
            f"sma{self.exit_sma}": exit_avg,
        }
        if holding:
            if close > exit_avg:
                return Signal(
                    False,
                    f"종가 {close} > SMA{self.exit_sma} {exit_avg:.2f}: 반등 청산",
                    indicators,
                )
            return Signal(
                True, f"보유 유지: 종가 {close} <= SMA{self.exit_sma} {exit_avg:.2f}", indicators
            )
        if close > trend and rsi < self.entry:
            return Signal(
                True,
                f"RSI{self.rsi} {rsi:.1f} < {self.entry}, 종가 > SMA{self.trend}: 눌림 매수",
                indicators,
            )
        return Signal(
            False, f"관망: RSI{self.rsi} {rsi:.1f}, SMA{self.trend} {trend:.2f}", indicators
        )


@dataclass(frozen=True)
class DipSaver:
    """나처럼 모으기: 매달 입금하고 사 모은다. 팔지 않는다.

    - 1년(high일) 종가 최고보다 dip% 이상 낮으면: 모아 둔 현금까지 모두 산다 (입금일이 아니어도)
    - SMA(sma) 보다 hot% 이상 높으면: 사지 않고 현금으로 모아 둔다 (hot=0이면 쉬지 않는다)
    - 그 밖에는: 입금일에 그달 입금액만큼 산다 (지난달 잔돈 포함, 고점 때 모아 둔 돈은 빼고)
    """

    deposit: int = 1350  # 매달 넣는 돈 (달러, 월 20만 엔 안팎)
    day: int = 25  # 입금일 (1~28)
    dip: int = 10  # % (10·15·20 중 고른다)
    hot: int = 10  # % (10·15·20, 0이면 고점에도 쉬지 않음)
    high: int = 252
    sma: int = 200
    name: ClassVar[str] = "dip_saver"

    def __post_init__(self) -> None:
        if self.deposit <= 0 or not 1 <= self.day <= 28:
            raise ValueError("deposit은 양수, day는 1~28이어야 합니다")
        if self.dip <= 0 or self.hot < 0 or self.high <= 1 or self.sma <= 1:
            raise ValueError("dip은 양수, hot은 0 이상, high, sma는 2 이상이어야 합니다")

    @property
    def params(self) -> dict[str, int]:
        return {
            "deposit": self.deposit,
            "day": self.day,
            "dip": self.dip,
            "hot": self.hot,
            "high": self.high,
            "sma": self.sma,
        }

    @property
    def warmup(self) -> int:
        return max(self.high, self.sma)

    @property
    def deposit_plan(self) -> DepositPlan:
        return DepositPlan(Decimal(self.deposit), self.day)

    def signal(self, history: Sequence[DailyBar], holding: bool) -> Signal | None:
        if len(history) < self.warmup:
            return None
        close = history[-1].close
        top = max(b.close for b in history[-self.high :])
        avg = _sma(history, self.sma)
        drawdown, premium = close / top - 1, close / avg - 1
        indicators = {
            f"high{self.high}": top,
            f"sma{self.sma}": avg,
            "drawdown": round(drawdown, 4),
            "premium": round(premium, 4),
        }
        state = f"최고 대비 {drawdown:.1%}, SMA{self.sma} 대비 {premium:+.1%}"
        if drawdown <= -Decimal(self.dip) / 100:
            return Signal(True, f"하락장 ({state}): 모은 현금 모두 매수", indicators, Spend.ALL)
        if self.hot and premium >= Decimal(self.hot) / 100:
            return Signal(True, f"고점 ({state}): 현금으로 모아 둠", indicators, Spend.NONE)
        return Signal(True, f"보통 ({state}): 입금액만큼 매수", indicators, Spend.DEPOSIT)


STRATEGIES: dict[str, Callable[..., Strategy]] = {
    "sma_cross": SmaCross,
    "donchian": DonchianBreakout,
    "trend_filter": TrendFilter,
    "rsi2": ConnorsRsi2,
    "dip_saver": DipSaver,
}
