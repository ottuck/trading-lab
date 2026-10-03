"""포트폴리오 데모용 예시 시세 (D1, project.md 11-1절).

토스 시세는 남에게 보여줄 수 없으므로 데모는 합성 일봉만 쓴다. 실제처럼 보이도록
시장 전체의 하루 움직임 하나를 만들고, 종목마다 그 움직임을 얼마나 따라가는지(베타)와
자기만의 흔들림을 더한다. 레버리지 ETF는 기초 지수의 하루 움직임을 배수만큼 따라간다.
상승장 사이에 급락·하락장을 넣어 나처럼 투자(하락장 몰아 사기)가 드러나게 한다.
같은 씨앗(seed)이면 늘 같은 값이다. 실제 가격과는 무관하다.
"""

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.domain.bars import DailyBar

DAYS_PER_YEAR = 252
DEMO_START = date(2006, 1, 3)  # 예시 시세의 첫 거래일


@dataclass(frozen=True)
class Shock:
    """이 기간 동안 시장이 모두 합쳐 move만큼 움직인다 (예: -0.45는 45% 하락)."""

    start: date
    end: date
    move: float


# 실제 역사와 비슷한 때에 둔 급락·하락장 (크기는 예시)
SHOCKS = (
    Shock(date(2007, 10, 10), date(2009, 3, 9), -0.50),
    Shock(date(2011, 7, 25), date(2011, 10, 3), -0.18),
    Shock(date(2015, 8, 17), date(2016, 2, 11), -0.13),
    Shock(date(2018, 10, 1), date(2018, 12, 24), -0.19),
    Shock(date(2020, 2, 20), date(2020, 3, 23), -0.33),
    Shock(date(2022, 1, 4), date(2022, 10, 12), -0.25),
    Shock(date(2025, 2, 20), date(2025, 4, 8), -0.18),
)


@dataclass(frozen=True)
class Spec:
    """예시 종목. base가 있으면 그 종목의 하루 움직임을 leverage배 따라간다 (레버리지 ETF)."""

    symbol: str
    listed: date
    start_price: float
    beta: float = 1.0  # 시장 움직임을 얼마나 따라가는지
    drift: float = 0.0  # 시장보다 해마다 더 오르는 정도
    vol: float = 0.0  # 자기만의 흔들림 (연 표준편차)
    base: str | None = None
    leverage: int = 1
    fee: float = 0.0095  # 레버리지 ETF 연 보수


SPECS = (
    Spec("VOO", date(2010, 9, 9), 100, beta=1.0, vol=0.01),
    Spec("QQQ", date(2006, 1, 3), 40, beta=1.2, drift=0.03, vol=0.06),
    Spec("NVDA", date(2006, 1, 3), 2, beta=1.8, drift=0.16, vol=0.35),
    Spec("GLD", date(2006, 1, 3), 50, beta=0.1, drift=0.03, vol=0.14),
    Spec("EWY", date(2006, 1, 3), 40, beta=1.0, drift=-0.03, vol=0.15),
    Spec("EWJ", date(2006, 1, 3), 50, beta=0.8, drift=-0.02, vol=0.10),
    # SOXL의 기초 지수 (화면에는 보이지 않는다)
    Spec("SEMI", date(2006, 1, 3), 100, beta=1.5, drift=0.05, vol=0.20),
    Spec("MAGS", date(2023, 4, 11), 20, beta=1.3, drift=0.05, vol=0.12),  # 상장 1년 남짓
    Spec("QLD", date(2006, 6, 21), 20, base="QQQ", leverage=2),
    Spec("TQQQ", date(2010, 2, 11), 1.5, base="QQQ", leverage=3),
    Spec("SOXL", date(2010, 3, 11), 3, base="SEMI", leverage=3),
)
HIDDEN = {"SEMI"}
LEVERAGE = {s.symbol: s.leverage for s in SPECS if s.leverage > 1}


# 급락·하락장이 아닌 평소 날의 하루 오름 (로그). 2006~2026 전체 시장이 연 9~10% 오르게 맞췄다.
# 기간 전체에서 거꾸로 계산하지 않고 상수로 두어, 기간을 늘려도 지난 값이 바뀌지 않는다.
CALM_DRIFT = 0.00084


def _market(sessions: Sequence[date], seed: int) -> list[float]:
    """시장 전체의 하루 로그 수익률. 연 15% 정도 흔들리고, 급락·하락장 때는 정해진 만큼 빠진다."""
    rng = random.Random(f"{seed}-market")
    daily = [rng.gauss(0, 0.15 / math.sqrt(DAYS_PER_YEAR)) for _ in sessions]
    shocked: set[int] = set()
    for shock in SHOCKS:
        idx = [i for i, d in enumerate(sessions) if shock.start <= d <= shock.end]
        if not idx:
            continue
        # 그 기간의 합이 shock.move가 되도록 하루하루에 나눠 얹는다 (흔들림은 그대로 둔 채)
        have = sum(daily[i] for i in idx)
        need = math.log(1 + shock.move)
        for i in idx:
            daily[i] += (need - have) / len(idx)
        shocked.update(idx)
    return [r if i in shocked else r + CALM_DRIFT for i, r in enumerate(daily)]


def demo_bars(sessions: Sequence[date], seed: int = 7) -> dict[str, list[DailyBar]]:
    """종목별 예시 일봉. sessions는 미국 거래일 (오름차순).

    종목마다 따로 난수를 써서, 기간을 뒤로 늘려도 앞의 값은 그대로다.
    """
    market = _market(sessions, seed)
    returns: dict[str, list[float]] = {}
    for spec in SPECS:
        if spec.base is None:
            rng = random.Random(f"{seed}-{spec.symbol}")
            noise = spec.vol / math.sqrt(DAYS_PER_YEAR)
            returns[spec.symbol] = [
                spec.beta * m + spec.drift / DAYS_PER_YEAR + rng.gauss(0, noise) for m in market
            ]
        else:
            # 레버리지 ETF: 기초 지수의 하루 수익률(단순 수익률)을 배수만큼, 보수를 빼고
            base = returns[spec.base]
            returns[spec.symbol] = [
                math.log(max(0.01, 1 + spec.leverage * math.expm1(r) - spec.fee / DAYS_PER_YEAR))
                for r in base
            ]

    out: dict[str, list[DailyBar]] = {}
    for spec in SPECS:
        if spec.symbol in HIDDEN:
            continue
        rng = random.Random(f"{seed}-{spec.symbol}-bars")
        bars: list[DailyBar] = []
        close = spec.start_price
        for d, r in zip(sessions, returns[spec.symbol], strict=True):
            if d < spec.listed:
                continue
            prev = close
            close = prev * math.exp(r) if bars else prev
            # 시가는 전날 종가 근처, 고가·저가는 시가·종가 바깥으로 조금
            open_ = prev * math.exp(rng.gauss(0, 0.003)) if bars else close
            high = max(open_, close) * (1 + abs(rng.gauss(0, 0.006)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, 0.006)))
            bars.append(
                DailyBar(
                    symbol=spec.symbol,
                    session_date=d,
                    open=_money(open_),
                    high=_money(high),
                    low=_money(low),
                    close=_money(close),
                    volume=Decimal(int(rng.uniform(2e6, 8e6))),
                )
            )
        out[spec.symbol] = bars
    return out


def _money(value: float) -> Decimal:
    """소수 넷째 자리까지 (값이 작은 레버리지 ETF도 하루 움직임이 반올림에 묻히지 않게)."""
    return Decimal(str(round(max(value, 0.0001), 4)))
