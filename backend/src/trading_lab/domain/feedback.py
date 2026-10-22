"""AI 봇에게 보여주는 피드백: 최근 판단과 그 뒤 결과 (project.md 14절 "피드백").

판단한 비중대로 그날 종가에 들고 있었다면 오늘 종가까지 몇 %였는지와, 같은 현금 비중으로 레버리지가
아닌 종목을 똑같이 나눠 들고 있었다면 몇 %였는지를 함께 보여준다. 기준에 레버리지와 0% 현금을 넣으면
오르는 장에서 늘 기준이 이겨 AI가 레버리지·현금 줄이기로 쏠릴 수 있어서, 종목 고르기만 견주게 했다.
체결·입금은 빼고 판단 자체만 본다 (현금은 0%).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from trading_lab.domain.bars import DailyBar

CALLS = 5  # 보여주는 최근 판단 수
CASH = "CASH"  # 판단 비중의 현금 키 (domain/candles.CASH와 같다)


@dataclass(frozen=True, slots=True)
class PastCall:
    """지난 판단 하나와 그 뒤 결과. 캔들분석에서는 날짜를 숨기고 종목은 오늘 글자로 바꾼다."""

    session_date: date | None
    days_ago: int  # 오늘까지 거래일 수
    weights: Mapping[str, int]  # 그날 정한 목표 비중 (현금은 CASH)
    result: Decimal  # 그 비중대로 들고 있었다면 오늘까지 %
    even: Decimal  # 같은 현금 비중으로 레버리지 아닌 종목을 똑같이 나눠 들고 있었다면 %

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "days_ago": self.days_ago,
            "weights": dict(self.weights),
            "result": str(self.result),
            "even": str(self.even),
        }
        if self.session_date is not None:
            out["session_date"] = self.session_date.isoformat()
        return out

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> PastCall:
        day = d.get("session_date")
        return cls(
            date.fromisoformat(day) if day else None,
            d["days_ago"],
            d["weights"],
            Decimal(d["result"]),
            Decimal(d["even"]),
        )


def _pct(value: Decimal) -> Decimal:
    return (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def past_calls(
    histories: Mapping[str, Sequence[DailyBar]],
    calls: Sequence[tuple[date, Mapping[str, int]]],
    leveraged: Collection[str] = (),
) -> tuple[PastCall, ...]:
    """histories의 마지막 봉(오늘)까지로 calls(오래된 것부터)의 결과를 잰다.

    그날 봉이 없는 종목은 빼고, 남은 종목이 하나도 없는 판단은 건너뛴다.
    """
    # 최근 판단만 보므로 끝에서부터 1년 치만 찾는다 (이력 전체를 매번 훑지 않게)
    index = {
        s: {b.session_date: len(bars) - 1 - k for k, b in enumerate(reversed(bars[-260:]))}
        for s, bars in histories.items()
    }
    out = []
    for day, weights in calls:
        moves: dict[str, Decimal] = {}
        days_ago = None
        for symbol, bars in histories.items():
            then = index[symbol].get(day)
            if then is None:
                continue
            moves[symbol] = bars[-1].close / bars[then].close - 1
            days_ago = len(bars) - 1 - then
        if not moves or days_ago is None:
            continue
        result = sum((Decimal(weights.get(s, 0)) / 100 * m for s, m in moves.items()), Decimal(0))
        plain = [m for s, m in moves.items() if s not in leveraged] or list(moves.values())
        invested = 1 - Decimal(weights.get(CASH, 0)) / 100
        even = invested * sum(plain, Decimal(0)) / len(plain)
        out.append(PastCall(day, days_ago, dict(weights), _pct(result), _pct(even)))
    return tuple(out)
