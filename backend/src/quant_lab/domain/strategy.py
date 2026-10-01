"""규칙 전략. 완료된 봉의 이력만 받아 '보유할지'를 판단한다.

전략은 주문 수량·가격을 정하지 않는다. 수량은 위험 규칙, 체결은 모의 브로커가 정한다.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import pairwise
from typing import ClassVar, Protocol

from quant_lab.domain.bars import DailyBar


@dataclass(frozen=True, slots=True)
class Signal:
    """long=True면 보유, False면 미보유가 목표. reason은 화면·로그에 그대로 보여준다."""

    long: bool
    reason: str
    indicators: dict[str, Decimal] = field(default_factory=dict)


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


STRATEGIES: dict[str, Callable[..., Strategy]] = {
    "sma_cross": SmaCross,
    "donchian": DonchianBreakout,
    "trend_filter": TrendFilter,
    "rsi2": ConnorsRsi2,
}
