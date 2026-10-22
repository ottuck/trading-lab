"""캔들분석 AI 봇의 입력: 익명화한 캔들 표와 되돌리기 (project.md 14절 "캔들분석 AI 봇").

AI는 종목 이름·날짜·실제 가격을 보지 않는다. 이름과 날짜를 보면 모델이 그 종목·그 시기에 시장이
어떻게 흘러갔는지 기억으로 답할 수 있어서다. 종목마다 일봉 90개와 주봉 52개를 판단일 종가 = 100인
지수로 바꾸고, 종목은 판단일마다 섞은 글자("종목 A", "종목 B", ...)로 부른다. 섞는 순서는
판단일로 정해서 같은 날을 다시 만들면 같은 표가 나온다.
"""

import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from trading_lab.domain.bars import DailyBar
from trading_lab.domain.feedback import PastCall
from trading_lab.domain.korean import has_batchim

CASH = "CASH"  # 현금 비중의 키 (종목과 함께 비중을 담는다)
DAILY_BARS = 90
WEEKLY_BARS = 52
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

Ohlc = tuple[Decimal, Decimal, Decimal, Decimal]  # 시가·고가·저가·종가 (지수)


@dataclass(frozen=True, slots=True)
class CandleBrief:
    """AI가 보는 종목 하나: 글자, 지수로 바꾼 일봉·주봉(오래된 것부터, 마지막이 판단일)."""

    label: str
    daily: tuple[Ohlc, ...]
    weekly: tuple[Ohlc, ...]  # 마지막 주는 판단일까지만
    weight_now: Decimal  # 지금 봇 자산에서 차지하는 비중 %
    leverage: Decimal | None = None  # 레버리지 ETF 배수 (위험 판단에 필요하고 종목을 드러내지 않음)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "leverage": str(self.leverage) if self.leverage is not None else None,
            "weight_now": str(self.weight_now),
            "daily": [[str(v) for v in row] for row in self.daily],
            "weekly": [[str(v) for v in row] for row in self.weekly],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CandleBrief:
        def rows(raw: list[list[str]]) -> tuple[Ohlc, ...]:
            return tuple((Decimal(o), Decimal(h), Decimal(lo), Decimal(c)) for o, h, lo, c in raw)

        lev = d.get("leverage")
        return cls(
            d["label"],
            rows(d["daily"]),
            rows(d["weekly"]),
            Decimal(d["weight_now"]),
            Decimal(lev) if lev is not None else None,
        )


@dataclass(frozen=True, slots=True)
class CandleRequest:
    """캔들분석 AI에게 넘기는 입력 전부. 종목 이름·날짜·실제 가격이 없다."""

    symbols: tuple[CandleBrief, ...]
    cash_weight: Decimal  # 지금 현금 비중 %
    previous: Mapping[str, int] | None = None  # 지난 판단의 목표 비중 (오늘 글자로 바꿈)
    feedback: tuple[PastCall, ...] = ()  # 최근 판단과 그 뒤 결과 (날짜 없이, 오늘 글자로)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbols": [s.as_dict() for s in self.symbols],
            "cash_weight": str(self.cash_weight),
            "previous": dict(self.previous) if self.previous is not None else None,
            "feedback": [c.as_dict() for c in self.feedback],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CandleRequest:
        return cls(
            tuple(CandleBrief.from_dict(s) for s in d["symbols"]),
            Decimal(d["cash_weight"]),
            d.get("previous"),
            tuple(PastCall.from_dict(c) for c in d.get("feedback", ())),
        )


@dataclass(frozen=True, slots=True)
class MaskedCandles:
    """익명 입력과 글자 → 종목 대응표. AI에게는 request만 넘긴다."""

    request: CandleRequest
    key: Mapping[str, str]  # {"A": "QQQ", ...}

    def as_dict(self) -> dict[str, Any]:
        return {**self.request.as_dict(), "key": dict(self.key)}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> MaskedCandles:
        return cls(CandleRequest.from_dict(d), d["key"])


def weekly(bars: Sequence[DailyBar]) -> list[Ohlc]:
    """일봉을 주(월~금)마다 시가·고가·저가·종가로 묶는다."""
    weeks: dict[tuple[int, int], list[DailyBar]] = {}
    for b in bars:
        year, week, _ = b.session_date.isocalendar()
        weeks.setdefault((year, week), []).append(b)
    return [
        (g[0].open, max(b.high for b in g), min(b.low for b in g), g[-1].close)
        for g in weeks.values()
    ]


def _index(rows: Iterable[Ohlc], base: Decimal) -> tuple[Ohlc, ...]:
    def f(v: Decimal) -> Decimal:
        return (v * 100 / base).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return tuple((f(o), f(h), f(lo), f(c)) for o, h, lo, c in rows)


def mask(
    histories: Mapping[str, Sequence[DailyBar]],
    weights_now: Mapping[str, Decimal],
    leverage: Mapping[str, Decimal | None],
    cash_weight: Decimal,
    previous: Mapping[str, int] | None,
    session_date: date,
    feedback: Sequence[PastCall] = (),
) -> MaskedCandles:
    """histories의 마지막 봉(판단일)까지로 익명 입력을 만든다."""
    symbols = sorted(histories)
    if len(symbols) > len(LABELS):
        raise ValueError(f"종목은 {len(LABELS)}개까지 익명화할 수 있습니다")
    random.Random(session_date.toordinal()).shuffle(symbols)
    key = dict(zip(LABELS, symbols, strict=False))
    label_of = {s: label for label, s in key.items()}
    briefs = []
    for label, symbol in key.items():
        bars = histories[symbol]
        base = bars[-1].close
        daily = ((b.open, b.high, b.low, b.close) for b in bars[-DAILY_BARS:])
        briefs.append(
            CandleBrief(
                label=label,
                daily=_index(daily, base),
                weekly=_index(weekly(bars)[-WEEKLY_BARS:], base),
                weight_now=weights_now[symbol],
                leverage=leverage.get(symbol),
            )
        )

    def relabel(weights: Mapping[str, int]) -> dict[str, int]:
        # 지금 종목이 아닌 이름은 넘기지 않는다 (이름이 드러난다)
        out = {label_of[s]: w for s, w in weights.items() if s in label_of}
        if CASH in weights:
            out[CASH] = weights[CASH]
        return out

    shown = relabel(previous) if previous is not None else None
    calls = tuple(
        PastCall(None, c.days_ago, relabel(c.weights), c.result, c.even) for c in feedback
    )
    return MaskedCandles(CandleRequest(tuple(briefs), cash_weight, shown, calls), key)


# AI가 종목을 부르는 꼴: "종목 C는", 목록으로 이어 쓴 "B와 C". 앞뒤에 영문·숫자가 붙은 글자("AI",
# "S&P 500")는 종목이 아니다. 뒤 조사는 종목 이름의 받침에 맞춰 다시 붙인다
_MENTION = re.compile(r"(?:종목 )?(?<![A-Za-z0-9])([A-Z])(?![A-Za-z0-9])(은|는|이|가|을|를|과|와)?")
_PARTICLES = {"은": "은는", "는": "은는", "이": "이가", "가": "이가", "을": "을를", "를": "을를"}
_PARTICLES |= {"과": "과와", "와": "과와"}


def unmask_text(text: str, key: Mapping[str, str]) -> str:
    """문장 안의 종목 글자("종목 X", 목록의 "X")를 종목 이름으로 바꾼다. 모르는 글자는 그대로."""

    def name(m: re.Match[str]) -> str:
        symbol = key.get(m.group(1))
        if symbol is None:
            return m.group(0)
        particle = m.group(2)
        if particle:
            pair = _PARTICLES[particle]
            particle = pair[0] if has_batchim(symbol) else pair[1]
        return symbol + (particle or "")

    return _MENTION.sub(name, text)
