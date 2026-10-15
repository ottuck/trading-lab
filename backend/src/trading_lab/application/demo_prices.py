"""포트폴리오 데모용 예시 시세 (D1, project.md 11-1절).

토스 시세는 남에게 보여줄 수 없으므로 데모는 합성 일봉만 쓴다. 하루하루의 값은 모두 난수로 만들고,
큰 흐름만 실제 역사를 닮게 한다.

- 큰 흐름: 2006년부터 2025년 4월까지는 널리 알려진 큰 고점·바닥(경유점)을 지나도록 그 사이를
  난수 흔들림으로 잇는다 (브라운 다리). 일봉을 따라 그리지는 않는다.
- 그 뒤: 상승장·보통 장·조정장·하락장이 실제와 비슷한 빈도로 바뀌는 가상의 미래.
  날짜순으로만 정하므로 기간이 늘어도 지난 값은 바뀌지 않는다.
- 잔결: 흔들림이 몰려 온다(GARCH), 가끔 아주 큰 날이 있다(t분포),
  위기 때는 모든 종목이 함께 요동친다.
- 종목: 시장 → 무리(기술주·반도체·금·한국·일본) → 종목 순으로 움직임을 더한다.
  개별 주식은 실적 발표 날 크게 갭이 난다.
  레버리지 ETF는 기초 지수의 하루 움직임을 배수만큼 따라간다.
- 캔들: 꼬리 길이와 시가 갭은 그날의 흔들림에 비례한다.

같은 씨앗(seed)이면 늘 같은 값이다. 실제 가격과는 무관하다.
"""

import itertools
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from trading_lab.domain.bars import DailyBar

DAYS_PER_YEAR = 252
DEMO_START = date(2006, 1, 3)  # 예시 시세의 첫 거래일
DEMO_USD_KRW = Decimal("1400")  # 데모의 고정 예시 환율 (실제 환율 아님, W1)

MARKET_VOL = 0.19  # 시장의 평소 흔들림 (연 표준편차). 경유점·국면의 stress가 이것을 몇 배로 키운다
GARCH = (
    0.06,
    0.91,
)  # 흔들림 몰림: 어제의 큰 움직임이 오늘 흔들림에 남는 정도, 흔들림이 이어지는 정도
TRIES = 40  # 경유점 구간마다 흔들림을 다시 뽑아 볼 횟수
SLACK = 0.03  # 구간 안에서 경유점 바깥으로 벗어나도 되는 정도 (로그, 약 3%)
NU = 6  # 꼬리 두께 (t분포 자유도). 작을수록 아주 큰 날이 잦다


@dataclass(frozen=True)
class Point:
    """경유점: 이 날 지수가 level(시작일 = 100)이 된다.

    stress는 앞 경유점에서 여기까지 평소보다 몇 배 요동쳤는지.
    """

    day: date
    level: float
    stress: float = 1.0


def _points(*rows: tuple[str, float, float]) -> tuple[Point, ...]:
    return tuple(Point(date.fromisoformat(d), level, stress) for d, level, stress in rows)


# 미국 대형주 시장의 큰 고점·바닥 (시작일 = 100, 대략). stress는 그 구간이 평소보다 몇 배 요동쳤는지
MARKET = _points(
    ("2006-01-03", 100, 1),
    ("2006-05-05", 104, 0.7),
    ("2006-06-13", 96, 1.2),
    ("2007-02-20", 115, 0.6),
    ("2007-03-05", 108, 1.3),
    ("2007-07-19", 122, 0.8),
    ("2007-08-15", 111, 1.7),
    ("2007-10-09", 123, 1.1),
    ("2008-03-10", 100, 1.5),
    ("2008-05-19", 112, 1.2),
    ("2008-07-15", 96, 1.4),
    ("2008-08-11", 103, 1.2),
    ("2008-09-15", 94, 1.4),
    ("2008-11-20", 59, 4.2),  # 리먼 뒤 두 달
    ("2009-01-06", 74, 2.8),
    ("2009-03-09", 53, 2.4),
    ("2009-06-12", 75, 2),
    ("2009-07-10", 69, 1.2),
    ("2010-01-19", 91, 0.9),
    ("2010-02-08", 83, 1.2),
    ("2010-04-23", 96, 0.8),
    ("2010-07-02", 81, 1.6),
    ("2011-02-18", 106, 0.8),
    ("2011-04-29", 108, 0.9),
    ("2011-08-08", 88, 2),
    ("2011-10-03", 87, 2.4),
    ("2012-04-02", 112, 0.9),
    ("2012-06-01", 101, 1),
    ("2012-09-14", 116, 0.7),
    ("2012-11-15", 107, 0.8),
    ("2013-05-21", 132, 0.7),
    ("2013-06-24", 124, 1.1),
    ("2013-12-31", 146, 0.6),
    ("2014-02-03", 137, 0.9),
    ("2014-09-18", 158, 0.6),
    ("2014-10-15", 147, 1.1),
    ("2015-05-21", 168, 0.7),
    ("2015-08-25", 147, 1.6),
    ("2015-11-03", 166, 1.2),
    ("2016-02-11", 144, 1.3),
    ("2016-06-08", 167, 0.8),
    ("2016-06-27", 158, 1.4),
    ("2016-11-04", 164, 0.6),
    ("2017-12-29", 211, 0.4),  # 아주 잔잔했던 해
    ("2018-01-26", 226, 0.7),
    ("2018-02-08", 203, 2.2),
    ("2018-09-20", 231, 0.8),
    ("2018-12-24", 185, 1.6),
    ("2019-04-30", 232, 0.9),
    ("2019-06-03", 216, 1),
    ("2019-07-26", 238, 0.6),
    ("2019-08-05", 224, 1.4),
    ("2020-02-19", 267, 0.7),
    ("2020-03-23", 176, 5),  # 한 달 만의 폭락
    ("2020-06-08", 255, 2.4),
    ("2020-06-26", 237, 1.6),
    ("2020-09-02", 282, 1),
    ("2020-10-30", 258, 1.4),
    ("2021-09-02", 358, 0.7),
    ("2021-10-04", 339, 1),
    ("2022-01-03", 378, 0.9),
    ("2022-03-08", 329, 1.6),
    ("2022-03-29", 365, 1.4),
    ("2022-06-16", 289, 1.6),
    ("2022-08-16", 339, 1.3),
    ("2022-10-12", 282, 1.6),
    ("2023-02-02", 329, 1.1),
    ("2023-03-13", 304, 1.1),
    ("2023-07-31", 362, 0.7),
    ("2023-10-27", 324, 0.9),
    ("2024-03-28", 414, 0.6),
    ("2024-04-19", 391, 0.9),
    ("2024-07-16", 447, 0.6),
    ("2024-08-05", 409, 1.4),
    ("2024-12-06", 480, 0.7),
    ("2025-01-13", 460, 1),
    ("2025-02-19", 484, 0.8),
    ("2025-04-08", 393, 2.2),  # 마지막 경유점. 이 뒤는 가상의 미래
)


def _anchors(*rows: tuple[str, float]) -> tuple[Point, ...]:
    return tuple(Point(date.fromisoformat(d), level) for d, level in rows)


@dataclass(frozen=True)
class Group:
    """종목 무리. 하루 움직임 = beta × 시장 + 무리만의 흔들림(vol) + 해마다 더 오르는 몫(drift).

    points는 무리 지수가 큰 사건 때 어디쯤이었는지(시작일 = 100, 대략)다. 그 사이는 시장을 따라가며
    맞춰지므로, 시장 경유점과 달리 구간의 고점·바닥일 필요는 없다.
    """

    beta: float
    vol: float = 0.0
    drift: float = 0.0
    points: tuple[Point, ...] = ()


GROUPS = {
    "us": Group(1.0),
    # 기술주 (나스닥100 같은 것): 2008은 시장만큼, 2020은 덜, 2022는 더 빠졌다
    "tech": Group(
        1.15,
        vol=0.07,
        drift=0.01,
        points=_anchors(
            ("2006-01-03", 100),
            ("2007-10-31", 128),
            ("2008-11-20", 63),
            ("2009-03-09", 65),
            ("2010-04-23", 116),
            ("2010-07-01", 100),
            ("2012-04-02", 158),
            ("2012-11-15", 144),
            ("2015-07-20", 265),
            ("2016-02-09", 223),
            ("2018-08-29", 433),
            ("2018-12-24", 335),
            ("2020-02-19", 551),
            ("2020-03-23", 395),
            ("2020-09-02", 705),
            ("2021-11-19", 949),
            ("2022-12-28", 605),
            ("2024-07-10", 1167),
            ("2024-08-07", 1028),
            ("2025-02-19", 1256),
            ("2025-04-08", 984),
        ),
    ),
    # 반도체 (SOXL의 기초 지수): 큰 하락장마다 시장의 두 배쯤 빠진다
    "semi": Group(
        1.4,
        vol=0.18,
        drift=0.0,
        points=_anchors(
            ("2006-01-03", 100),
            ("2007-07-16", 106),
            ("2008-11-20", 34),
            ("2010-04-23", 80),
            ("2011-08-08", 66),
            ("2015-06-01", 146),
            ("2016-02-11", 112),
            ("2018-03-12", 280),
            ("2018-12-24", 215),
            ("2020-02-19", 400),
            ("2020-03-23", 265),
            ("2021-12-27", 800),
            ("2022-10-13", 430),
            ("2024-07-10", 1180),
            ("2024-08-07", 880),
            ("2025-04-08", 740),
        ),
    ),
    # 금: 2008 폭락 땐 덜 빠지고, 2011·2020·2024에 크게 올랐다
    "gold": Group(
        0.15,
        vol=0.16,
        drift=0.05,
        points=_anchors(
            ("2006-01-03", 100),
            ("2008-03-17", 189),
            ("2008-10-24", 128),
            ("2011-09-06", 349),
            ("2013-06-27", 221),
            ("2015-12-17", 191),
            ("2020-08-06", 366),
            ("2022-09-26", 289),
            ("2024-10-30", 481),
            ("2025-04-08", 519),
        ),
    ),
    # 한국: 2008에 시장보다 훨씬 깊이(-70%) 빠졌다
    "korea": Group(
        0.9,
        vol=0.25,
        drift=-0.04,
        points=_anchors(
            ("2006-01-03", 100),
            ("2007-10-31", 178),
            ("2008-10-24", 53),
            ("2011-04-29", 156),
            ("2011-09-26", 104),
            ("2018-01-26", 178),
            ("2020-03-23", 89),
            ("2021-02-16", 211),
            ("2022-09-30", 107),
            ("2024-07-10", 147),
            ("2025-04-08", 111),
        ),
    ),
    # 일본: 20년 동안 거의 제자리
    "japan": Group(
        0.75,
        vol=0.13,
        drift=-0.04,
        points=_anchors(
            ("2006-01-03", 100),
            ("2007-02-26", 109),
            ("2009-03-09", 56),
            ("2013-05-22", 87),
            ("2018-01-26", 113),
            ("2020-03-23", 84),
            ("2021-02-16", 127),
            ("2022-09-30", 85),
            ("2024-07-10", 133),
            ("2025-04-08", 113),
        ),
    ),
}


@dataclass(frozen=True)
class Spec:
    """예시 종목. base가 있으면 그 종목의 하루 움직임을 leverage배 따라간다 (레버리지 ETF)."""

    symbol: str
    listed: date
    start_price: float
    group: str = "us"
    beta: float = 1.0  # 무리 움직임을 얼마나 따라가는지
    drift: float = 0.0  # 무리보다 해마다 더 오르는 정도
    vol: float = 0.0  # 자기만의 흔들림 (연 표준편차)
    earnings: bool = False  # 개별 주식: 실적 발표 날(2·5·8·11월 22일 무렵) 크게 갭
    # 하루 움직임 중 밤사이(시가 갭)에 나는 몫. 해외 시장·금은 미국 장 밖에서 더 움직인다
    overnight: float = 0.4
    points: tuple[Point, ...] = ()  # 개별 주식의 큰 사건 때 위치 (시작일 = 100, 대략)
    base: str | None = None
    leverage: int = 1
    fee: float = 0.0095  # 레버리지 ETF 연 보수


SPECS = (
    Spec("VOO", date(2010, 9, 9), 100, vol=0.01),
    Spec("QQQ", date(2006, 1, 3), 40, group="tech", vol=0.02),
    Spec(
        "NVDA",
        date(2006, 1, 3),
        2,
        # 반도체지만 나스닥100에서 큰 몫이라 QQQ와 더 함께 움직인다 (실제 상관 QQQ 0.74, SOXL 0.67)
        group="tech",
        beta=1.5,
        drift=-0.02,
        vol=0.27,
        earnings=True,
        # 2008 -85%, 2018 말 -55%, 2022 -66%, 그 뒤 AI 붐
        points=_anchors(
            ("2006-01-03", 100),
            ("2007-10-31", 325),
            ("2008-11-20", 47),
            ("2015-12-31", 270),
            ("2018-10-01", 2370),
            ("2018-12-24", 1060),
            ("2021-11-29", 10900),
            ("2022-10-13", 3670),
            ("2024-06-18", 44600),
            ("2025-01-06", 48900),
            ("2025-04-04", 30800),
        ),
    ),
    Spec("GLD", date(2006, 1, 3), 50, group="gold", vol=0.02, overnight=0.6),
    Spec("EWY", date(2006, 1, 3), 40, group="korea", vol=0.03, overnight=0.6),
    Spec("EWJ", date(2006, 1, 3), 50, group="japan", vol=0.03, overnight=0.6),
    # SOXL의 기초 지수 (화면에는 보이지 않는다)
    Spec("SEMI", date(2006, 1, 3), 100, group="semi", vol=0.03),
    Spec("MAGS", date(2023, 4, 11), 20, group="tech", beta=1.15, vol=0.08),
    Spec("QLD", date(2006, 6, 21), 20, base="QQQ", leverage=2),
    Spec("TQQQ", date(2010, 2, 11), 1.5, base="QQQ", leverage=3),
    Spec("SOXL", date(2010, 3, 11), 3, base="SEMI", leverage=3),
)
HIDDEN = {"SEMI"}
LEVERAGE = {s.symbol: s.leverage for s in SPECS if s.leverage > 1}

# 마지막 경유점 뒤의 가상 시장. 평소 국면 (연 기대 수익, 흔들림 배수): 순한 상승장 / 보통 장
STEADY = ((0.16, 0.8), (0.07, 1.0))
SWITCH = 1 / 300  # 평소 국면이 하루에 바뀔 확률 (평균 1년 남짓)
# 조정장·하락장: 하루에 시작될 확률, 빠지는 깊이, 빠지는 기간(거래일), 흔들림 배수.
# 평균 1년 반에 조정, 6년에 하락장 한 번
DROPS = (
    (1 / 380, (0.10, 0.18), (15, 45), 1.2),
    (1 / 1500, (0.22, 0.32), (100, 220), 1.3),
)
# 마지막 경유점(2025년 4월 바닥)에서 시작하는 반등: 기간(거래일)과 되찾는 정도(로그), 흔들림 배수
FIRST_REBOUND = (55, math.log(484 / 393), 1.1)
# 가상 미래의 씨앗. 앞 1년 반(2025-04 ~ 2026-10)이 무난한 것(-16% 조정 한 번, +30% 남짓)으로 골랐다.
# 같은 빈도라도 씨앗에 따라 지금이 폭락장 한가운데일 수 있어서다
FUTURE = 19


def _t(rng: random.Random) -> float:
    """평균 0, 분산 1인 t분포 난수 (정규분포보다 아주 큰 값이 잦다). 표준편차 5배에서 자른다."""
    chi = rng.gammavariate(NU / 2, 2)
    x = rng.gauss(0, 1) / math.sqrt(chi / NU) * math.sqrt((NU - 2) / NU)
    return max(-5.0, min(5.0, x))


def _segments(
    sessions: Sequence[date], points: Sequence[Point]
) -> list[tuple[Point, Point, list[int]]]:
    """경유점 구간마다 (앞 경유점, 뒤 경유점, 그 구간에 든 날의 번호)."""
    out = []
    for p0, p1 in itertools.pairwise(points):
        idx = [i for i, d in enumerate(sessions) if p0.day < d <= p1.day]
        if idx:
            out.append((p0, p1, idx))
    return out


def _pin(moves: list[float], p0: Point, p1: Point) -> tuple[list[float], float]:
    """하루 움직임에 같은 값을 더해 두 경유점을 지나게 한다.

    구간 안에서 경유점 바깥으로 가장 멀리 간 정도(로그)도 돌려준다.
    """
    total = math.log(p1.level / p0.level)
    gap = (total - sum(moves)) / len(moves)
    out = [m + gap for m in moves]
    lo, hi = sorted((0.0, total))
    level, worst = 0.0, 0.0
    for m in out:
        level += m
        worst = max(worst, level - hi, lo - level)
    return out, worst


def _fit[T](
    draw: Callable[[random.Random], tuple[list[float], T]], rng: random.Random, p0: Point, p1: Point
) -> tuple[list[float], T]:
    """구간의 흔들림을 몇 번까지 다시 뽑아, 경유점 바깥으로 덜 벗어나는 것을 고른다.

    실제 역사의 경유점은 그 구간의 고점·바닥이라,
    그 사이 흔들림이 경유점 바깥으로 멀리 가면 어색하다.
    """
    best: tuple[float, list[float], T] | None = None
    for _ in range(TRIES):
        moves, extra = draw(rng)
        pinned, worst = _pin(moves, p0, p1)
        if best is None or worst < best[0]:
            best = (worst, pinned, extra)
        if worst <= SLACK:
            break
    assert best is not None
    return best[1], best[2]


def _drop(
    rng: random.Random, kind: tuple[float, tuple[float, float], tuple[int, int], float]
) -> list[tuple[float, float]]:
    """조정장(또는 하락장)과 그 뒤 반등의 하루하루 (기대 로그 수익, 흔들림 배수).

    빠진 만큼을 두 배 기간에 걸쳐 조금 넘게 되찾는다.
    """
    _, (lo, hi), (short, long), stress = kind
    fall = math.log(1 - rng.uniform(lo, hi))
    days = rng.randint(short, long)
    back = int(days * 2)
    return [(fall / days, stress)] * days + [(-fall * 1.1 / back, (1 + stress) / 2)] * back


def _future(n: int, rng: random.Random) -> list[tuple[float, float]]:
    """마지막 경유점 뒤 n일의 (기대 로그 수익, 흔들림 배수). 하루씩 앞으로만 정한다."""
    days, gain, stress = FIRST_REBOUND
    queue = [(gain / days, stress)] * days
    steady = STEADY[0]
    out: list[tuple[float, float]] = []
    while len(out) < n:
        if queue:
            out.append(queue.pop(0))
            continue
        u = rng.random()
        for drop in DROPS:
            if u < drop[0]:
                queue = _drop(rng, drop)
                break
            u -= drop[0]
        else:
            if u < SWITCH:
                steady = STEADY[1] if steady == STEADY[0] else STEADY[0]
        if not queue:
            out.append((steady[0] / DAYS_PER_YEAR, steady[1]))
    return out


def _market(sessions: Sequence[date], seed: int) -> tuple[list[float], list[float]]:
    """시장의 하루 로그 수익률과 그날의 흔들림 배수(GARCH × 구간·국면).

    경유점 구간은 구간마다 따로 난수를 뽑고, 마지막 경유점 뒤는 날짜순으로 뽑는다.
    """
    alpha, beta = GARCH
    scale = MARKET_VOL / math.sqrt(DAYS_PER_YEAR)

    def walk(
        z: Sequence[float], stress: Sequence[float], h: float
    ) -> tuple[list[float], list[float], float]:
        """흔들림 몰림(GARCH): 큰 움직임 다음 날은 흔들림이 커지고 천천히 가라앉는다."""
        vols, moves = [], []
        for zi, si in zip(z, stress, strict=True):
            vols.append(math.sqrt(h) * si)
            moves.append(scale * vols[-1] * zi)
            h = (1 - alpha - beta) + alpha * zi * zi * h + beta * h
        return vols, moves, h

    n = len(sessions)
    vol, moves = [1.0] * n, [0.0] * n
    h = 1.0
    for p0, p1, idx in _segments(sessions, MARKET):

        def draw(
            rng: random.Random, idx: list[int] = idx, stress: float = p1.stress, h: float = h
        ) -> tuple[list[float], tuple[list[float], float]]:
            vols, ms, h_end = walk([_t(rng) for _ in idx], [stress] * len(idx), h)
            return ms, (vols, h_end)

        ms, (vols, h) = _fit(draw, random.Random(f"{seed}-market-{p1.day}"), p0, p1)
        for i, v, m in zip(idx, vols, ms, strict=True):
            vol[i], moves[i] = v, m

    later = [i for i, d in enumerate(sessions) if d > MARKET[-1].day]
    plan = _future(len(later), random.Random(f"{seed}-future-{FUTURE}"))
    rng = random.Random(f"{seed}-market-future")
    vols, ms, _ = walk([_t(rng) for _ in later], [si for _, si in plan], h)
    for i, v, m, (mu, _) in zip(later, vols, ms, plan, strict=True):
        vol[i], moves[i] = v, m + mu
    return moves, vol


def _series(
    sessions: Sequence[date],
    points: Sequence[Point],
    draw: Callable[[random.Random, Sequence[int]], list[float]],
    key: str,
) -> list[float]:
    """하루 로그 수익률. 경유점 구간은 구간마다 따로 난수를 뽑아 경유점을 지나게 맞추고,
    나머지 날(마지막 경유점 뒤)은 날짜순으로 뽑는다. 그래서 기간을 늘려도 앞의 값은 그대로다."""
    out = [0.0] * len(sessions)
    fitted: set[int] = set()
    for p0, p1, idx in _segments(sessions, points):
        ms, _ = _pin(draw(random.Random(f"{key}-{p1.day}"), idx), p0, p1)
        for i, m in zip(idx, ms, strict=True):
            out[i] = m
        fitted.update(idx)
    rest = [i for i in range(len(sessions)) if i not in fitted]
    for i, m in zip(rest, draw(random.Random(key), rest), strict=True):
        out[i] = m
    return out


def _group(
    name: str, sessions: Sequence[date], market: Sequence[float], vol: Sequence[float], seed: int
) -> list[float]:
    """무리의 하루 로그 수익률. 무리만의 흔들림은 위기 때 덜 커진다 (위기엔 모두 함께 움직인다)."""
    g = GROUPS[name]
    scale = g.vol / math.sqrt(DAYS_PER_YEAR)

    def draw(rng: random.Random, idx: Sequence[int]) -> list[float]:
        return [
            g.beta * market[i] + g.drift / DAYS_PER_YEAR + scale * math.sqrt(vol[i]) * _t(rng)
            for i in idx
        ]

    return _series(sessions, g.points, draw, f"{seed}-group-{name}")


def _earnings(sessions: Sequence[date]) -> set[int]:
    """실적 발표 날: 2·5·8·11월마다 22일 이후 첫 거래일."""
    out: set[int] = set()
    seen: set[tuple[int, int]] = set()
    for i, d in enumerate(sessions):
        if d.month in (2, 5, 8, 11) and d.day >= 22 and (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            out.add(i)
    return out


def _spread(spec: Spec) -> float:
    """종목의 평소 흔들림 (연 표준편차, 캔들 꼬리 길이에 쓴다)."""
    if spec.base is not None:
        return spec.leverage * _spread(next(s for s in SPECS if s.symbol == spec.base))
    g = GROUPS[spec.group]
    return math.hypot(spec.beta * g.beta * MARKET_VOL, spec.beta * g.vol, spec.vol)


def demo_bars(sessions: Sequence[date], seed: int = 7) -> dict[str, list[DailyBar]]:
    """종목별 예시 일봉. sessions는 미국 거래일 (오름차순).

    난수는 종목·무리마다 따로 날짜순으로 뽑아서, 기간을 뒤로 늘려도 앞의 값은 그대로다.
    """
    market, vol = _market(sessions, seed)
    groups = {name: _group(name, sessions, market, vol, seed) for name in GROUPS}

    earnings = _earnings(sessions)
    returns: dict[str, list[float]] = {}
    jumps: dict[str, list[float]] = {}
    for spec in SPECS:
        if spec.base is None:
            gaps = random.Random(f"{seed}-{spec.symbol}-earnings")
            jump = [
                0.05 * _t(gaps) if spec.earnings and i in earnings else 0.0
                for i in range(len(sessions))
            ]
            group = groups[spec.group]
            scale = spec.vol / math.sqrt(DAYS_PER_YEAR)

            def draw(
                rng: random.Random,
                idx: Sequence[int],
                spec: Spec = spec,
                group: list[float] = group,
                jump: list[float] = jump,
                scale: float = scale,
            ) -> list[float]:
                return [
                    spec.beta * group[i]
                    + spec.drift / DAYS_PER_YEAR
                    + scale * math.sqrt(max(vol[i], 1.0)) * rng.gauss(0, 1)
                    + jump[i]
                    for i in idx
                ]

            returns[spec.symbol] = _series(sessions, spec.points, draw, f"{seed}-{spec.symbol}")
            jumps[spec.symbol] = jump
        else:
            # 레버리지 ETF: 기초 지수의 하루 수익률(단순 수익률)을 배수만큼, 보수를 빼고
            base = returns[spec.base]
            returns[spec.symbol] = [
                math.log(max(0.01, 1 + spec.leverage * math.expm1(r) - spec.fee / DAYS_PER_YEAR))
                for r in base
            ]
            jumps[spec.symbol] = [0.0] * len(sessions)

    out: dict[str, list[DailyBar]] = {}
    for spec in SPECS:
        if spec.symbol in HIDDEN:
            continue
        rng = random.Random(f"{seed}-{spec.symbol}-bars")
        daily = _spread(spec) / math.sqrt(DAYS_PER_YEAR)
        bars: list[DailyBar] = []
        close = spec.start_price
        for d, r, j, v in zip(sessions, returns[spec.symbol], jumps[spec.symbol], vol, strict=True):
            if d < spec.listed:
                continue
            sd = daily * v  # 그날의 흔들림
            # 장중 꼬리 (밤사이에 많이 움직이는 종목은 짧다)
            wick = 0.6 * sd * (1 - spec.overnight)
            prev = close
            if bars:
                close = prev * math.exp(r)
                # 시가: 밤사이 움직임(그날 움직임의 일부, 실적 갭은 전부)
                night = spec.overnight * (r - j) + rng.gauss(0, 0.4 * sd)
                open_ = prev * math.exp(j + night)
            else:
                open_ = close
            high = max(open_, close) * math.exp(abs(rng.gauss(0, wick)))
            low = min(open_, close) * math.exp(-abs(rng.gauss(0, wick)))
            bars.append(
                DailyBar(
                    symbol=spec.symbol,
                    session_date=d,
                    open=_money(open_),
                    high=_money(high),
                    low=_money(low),
                    close=_money(close),
                    volume=Decimal(int(rng.uniform(2e6, 8e6) * min(v, 4))),
                )
            )
        out[spec.symbol] = bars
    return out


def _money(value: float) -> Decimal:
    """소수 넷째 자리까지 (값이 작은 레버리지 ETF도 하루 움직임이 반올림에 묻히지 않게)."""
    return Decimal(str(round(max(value, 0.0001), 4)))
