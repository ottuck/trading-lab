"""규칙 전략. 완료된 봉의 이력만 받아 '보유할지'를 판단한다.

전략은 주문 수량·가격을 정하지 않는다. 수량은 위험 규칙, 체결은 모의 브로커가 정한다.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
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


STRATEGIES: dict[str, Callable[..., Strategy]] = {
    "sma_cross": SmaCross,
    "donchian": DonchianBreakout,
}
