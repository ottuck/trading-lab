"""포트폴리오 데모의 예시 AI 판단 (데모에는 AI 키가 없다, project.md 11-1절).

실제 AI가 아니라 정해진 규칙으로 domain/advisor.py 규약에 맞는 판단을 만든다. 같은 입력이면
늘 같은 판단이고 비용은 0이다. 화면은 "예시 판단"이라고 한 번만 알리고, 판단 문장(summary)은
실제 봇과 같은 말투로 쓴다 (시장 분위기 지수도 데모 가격으로 만든 예시, 2026-10-22 사용자 결정).

규칙: 레버리지가 아닌 종목 중 200일 평균 위에 있고 3개월 수익이 플러스인 종목을 3개월 수익이 큰
순서로 5개까지 담는다. 변동성이 작을수록 많이 담되 한 종목은 30%까지, 현금은 20% 이상 남긴다
(담을 종목이 없으면 모두 현금).
담을 종목이 지난 판단과 같으면 지난 비중을 그대로 둔다 (실제 AI 지침처럼 이유 없이 바꾸지 않음).
근거는 실제 봇처럼 뉴스로 보여주되, 데모 가격 흐름에 맞춰 지어낸 "예시 뉴스"다 (실제 매체 이름·
기사 주소는 쓰지 않고 출처 자리에 "예시 뉴스"라고 밝힌다, 2026-10-22 사용자 결정).

캔들분석 AI 봇의 예시 판단(DemoCandleAdvisor)은 실제 봇처럼 익명 캔들 표만 받는다. 레버리지가
아닌 종목 중 판단일 지수가 90일 평균 위이고 최근 20일 수익이 플러스인 종목을 20일 수익이 큰
순서로 4개까지 똑같이 나눠 담는다 (한 종목 30%까지, 현금 20% 이상, 지난 판단 유지는 같다).
근거는 차트에서 본 것만 쓴다.
"""

from decimal import ROUND_DOWN, Decimal

from trading_lab.application.messages import obj, subj
from trading_lab.domain.advisor import (
    CASH,
    Advice,
    AdviceRequest,
    AdviceResult,
    AdviceUsage,
    Basis,
    SymbolBrief,
)
from trading_lab.domain.candles import CandleBrief, CandleRequest

SOURCE = "demo"
# 예시 판단의 문장을 바꾸면 올린다 (seed-demo가 예전 버전의 예시 AI 봇을 처음부터 다시 채운다)
PROMPT_VERSION = "demo-2"
CANDLE_PROMPT_VERSION = "demo-candle-2"
EXAMPLE_NEWS = "예시 뉴스"  # 근거의 출처 자리 (데모 가격에 맞춰 지어낸 소식)
MAX_PICKS = 5
MAX_WEIGHT = 30  # 한 종목에 담는 최대 비중 (%)


def _rising(b: SymbolBrief) -> bool:
    return (
        not (b.leverage and b.leverage > 1)
        and b.vs_sma200 is not None
        and b.vs_sma200 > 0
        and (b.return_3m or 0) > 0
    )


def _split(picks: list[SymbolBrief], total: int) -> dict[str, int]:
    """total(%)를 변동성의 역수 비율로 정수로 나눈다 (나머지는 앞 종목부터 1%씩)."""
    inv = {b.symbol: 1 / max(b.volatility, Decimal(1)) for b in picks}
    whole = sum(inv.values(), Decimal(0))
    out = {s: int((total * v / whole).to_integral_value(ROUND_DOWN)) for s, v in inv.items()}
    for s in list(out)[: total - sum(out.values())]:
        out[s] += 1
    return {s: min(w, MAX_WEIGHT) for s, w in out.items()}


def _reason(b: SymbolBrief, weight: int) -> str:
    if b.leverage and b.leverage > 1:
        return f"하락장에서 손실이 {b.leverage.normalize():f}배로 커지는 상품이라 담지 않아요."
    if weight:
        return (
            f"200일 평균보다 {b.vs_sma200}% 위에 있고 3개월 동안 {b.return_3m}% 올라 "
            f"{weight}% 담아요."
        )
    if b.vs_sma200 is not None and b.vs_sma200 <= 0:
        return "200일 평균보다 아래에 있어 지금은 담지 않아요."
    return "오르는 흐름이 약해서 지금은 담지 않아요."


class DemoAdvisor:
    """규칙으로 만든 예시 판단. 데모 시세(seed-demo)에서만 쓴다."""

    @property
    def source(self) -> str:
        return SOURCE

    def advise(self, request: AdviceRequest) -> AdviceResult:
        rising = sorted(
            (b for b in request.symbols if _rising(b)),
            key=lambda b: b.return_3m or 0,
            reverse=True,
        )[:MAX_PICKS]
        cash = 20 if rising else 100
        weights = {b.symbol: 0 for b in request.symbols}
        previous = dict(request.previous or {})
        if previous and {s for s, w in previous.items() if w and s != CASH} == {
            b.symbol for b in rising
        }:
            weights |= {s: w for s, w in previous.items() if s != CASH}
            cash = previous.get(CASH, cash)
            kept = True
        else:
            weights |= _split(rising, 100 - cash) if rising else {}
            cash = 100 - sum(weights.values())  # 한 종목 상한에 걸려 못 담은 몫은 현금
            kept = False
        reasons = {b.symbol: _reason(b, weights[b.symbol]) for b in request.symbols}
        reasons[CASH] = "갑자기 떨어질 때와 다음 달 사기를 위해 남겨 둬요."
        basis = tuple(Basis(t, title=EXAMPLE_NEWS) for t in _news(request, rising))
        advice = Advice(
            {**weights, CASH: cash},
            reasons,
            _summary(request, rising, kept, cash),
            decision=_decision(kept, [b.symbol for b in rising], cash),
            basis=basis,
        )
        return AdviceResult(advice, AdviceUsage("demo-rules", 0, 0, 0, Decimal(0)), PROMPT_VERSION)


def _plain(request: AdviceRequest) -> list[SymbolBrief]:
    return [b for b in request.symbols if not (b.leverage and b.leverage > 1)]


def _month(request: AdviceRequest) -> float:
    """레버리지 아닌 종목의 한 달 평균 수익 (%) = 예시 시장 분위기."""
    month = [b.return_1m for b in _plain(request) if b.return_1m is not None]
    return float(sum(month, Decimal(0)) / len(month)) if month else 0.0


def _fear_greed(request: AdviceRequest) -> int:
    """예시 시장 분위기 지수 (0 겁먹음 ~ 100 욕심): 한 달 수익과 200일 평균과의 거리로 만든다."""
    trend = [b.vs_sma200 for b in _plain(request) if b.vs_sma200 is not None]
    t = float(sum(trend, Decimal(0)) / len(trend)) if trend else 0.0
    return max(5, min(95, round(50 + 3 * _month(request) + t)))


_FEAR_WORDS = ((25, "몹시 겁먹은"), (45, "겁먹은"), (56, "중립에 가까운"), (75, "욕심이 커진"))
_MARKET_BRIEF = {
    "up": "증시는 한 달 새 {m:+.1f}% 오르며 오르는 쪽에 무게가 실려 있습니다.",
    "down": "증시는 한 달 새 {m:.1f}% 내리며 흔들리고 있습니다.",
    "flat": "증시는 한 달 동안 큰 방향 없이 움직였습니다 ({m:+.1f}%).",
}


def _ro(n: int) -> str:
    """숫자 뒤 조사: 23으로, 25로 (끝자리 0·3·6만 받침이 'ㄹ'이 아니다)."""
    return "으로" if n % 10 in (0, 3, 6) else "로"


def _summary(request: AdviceRequest, rising: list[SymbolBrief], kept: bool, cash: int) -> str:
    """실제 시장분석 봇처럼: 시장 분위기 지수 → 시장 흐름 → 눈에 띄는 종목 → 한 일."""
    fg = _fear_greed(request)
    word = next((w for limit, w in _FEAR_WORDS if fg < limit), "몹시 욕심이 커진")
    out = [
        f"시장 분위기 지수는 약 {fg}{_ro(fg)} {word} 편입니다.",
        _MARKET_BRIEF[_mood(request)].format(m=_month(request)),
    ]
    weak = [b for b in _plain(request) if b.vs_sma200 is not None and b.vs_sma200 < 0]
    if rising:
        r = float(rising[0].return_3m or 0)
        out.append(f"{subj(rising[0].symbol)} 석 달 동안 {r:+.1f}% 올라 가장 강합니다.")
    if weak:
        names = "·".join(b.symbol for b in weak[:3])
        out.append(f"반면 {subj(names)} 200일 평균 아래로 내려와 약합니다.")
    if kept:
        out.append(
            f"지난 판단을 바꿀 분명한 이유가 없어 비중을 그대로 유지하고, 현금 {cash}%로 변동에 "
            "대비합니다."
        )
    elif rising:
        names = ", ".join(b.symbol for b in rising)
        out.append(f"오르는 흐름의 {obj(names)} 담고 현금 {cash}%로 변동에 대비합니다.")
    else:
        out.append("오르는 종목이 없어 모두 현금으로 두고 기다립니다.")
    return " ".join(out)


def _mood(request: AdviceRequest) -> str:
    m = _month(request)
    return "up" if m > 2 else "down" if m < -2 else "flat"


# 예시 뉴스: 시장 분위기(레버리지 아닌 종목의 한 달 평균 수익)마다 두 가지 중 판단일로 고른다
_MARKET_NEWS = {
    "up": (
        "대형 기술 기업들의 실적이 예상보다 좋게 나오며 미국 증시가 한 달 새 {m:+.1f}% 올랐어요. "
        "당분간 오르는 쪽에 무게가 실려요.",
        "물가가 예상만큼 내려오며 금리 인하 기대가 커졌고, 증시가 한 달 새 {m:+.1f}% 올랐어요.",
    ),
    "down": (
        "금리가 생각보다 오래 높게 유지될 거라는 전망에 증시가 한 달 새 {m:.1f}% 내렸어요. "
        "많이 흔들리는 종목에는 부담이에요.",
        "경기가 식고 있다는 지표가 잇따르며 증시가 한 달 새 {m:.1f}% 내렸어요.",
    ),
    "flat": (
        "물가 발표와 중앙은행 회의를 앞두고 증시가 한 달 동안 큰 방향 없이 움직였어요 ({m:+.1f}%).",
        "기업 실적 발표가 엇갈리며 증시가 한 달 동안 제자리걸음을 했어요 ({m:+.1f}%).",
    ),
}
_PICK_NEWS = (
    "{s} 쪽 이익 전망이 좋아졌다는 소식이 이어지며 석 달 동안 {r:+.1f}% 올랐어요.",
    "{s} 쪽으로 투자 돈이 몰리고 있다는 소식이 이어졌어요. 석 달 수익은 {r:+.1f}%예요.",
)
_WEAK_NEWS = "{s} 쪽 전망이 어두워졌다는 소식에 200일 평균 아래로 내려왔어요."


def _news(request: AdviceRequest, rising: list[SymbolBrief]) -> list[str]:
    """데모 가격 흐름에 맞춘 예시 뉴스 2~3개: 시장 분위기, 가장 강한 종목, 약해진 종목."""
    plain = _plain(request)
    pick = request.session_date.toordinal() % 2
    out = [_MARKET_NEWS[_mood(request)][pick].format(m=_month(request))]
    if rising:
        out.append(_PICK_NEWS[pick].format(s=rising[0].symbol, r=float(rising[0].return_3m or 0)))
    weak = [b for b in plain if b.vs_sma200 is not None and b.vs_sma200 < 0]
    if weak:
        out.append(_WEAK_NEWS.format(s=min(weak, key=lambda b: b.vs_sma200 or 0).symbol))
    return out


def _decision(kept: bool, names: list[str], cash: int) -> str:
    if kept:
        return "지난 비중을 그대로 유지했어요."
    if not names:
        return "오르는 종목이 없어 모두 현금으로 뒀어요."
    return f"{obj(', '.join(names))} 담고 현금 {cash}%를 남겼어요."


CANDLE_PICKS = 4
SHORT = 20  # 최근 흐름을 보는 거래일 수


def _short_return(b: CandleBrief) -> Decimal | None:
    closes = [row[3] for row in b.daily]
    if len(closes) <= SHORT:
        return None
    return (closes[-1] / closes[-1 - SHORT] - 1) * 100


def _above_average(b: CandleBrief) -> bool:
    closes = [row[3] for row in b.daily]
    return closes[-1] > sum(closes, Decimal(0)) / len(closes)


def _leveraged(b: CandleBrief) -> bool:
    return bool(b.leverage and b.leverage > 1)


def _candle_reason(b: CandleBrief, weight: int, ret: Decimal | None) -> str:
    if _leveraged(b):
        assert b.leverage is not None
        return f"하락장에서 손실이 {b.leverage.normalize():f}배로 커지는 상품이라 담지 않아요."
    if weight:
        return f"최근 20일 동안 {ret:.1f}% 올랐고 90일 평균보다 위에 있어 {weight}% 담아요."
    if not _above_average(b):
        return "90일 평균보다 아래에 있어 지금은 담지 않아요."
    if ret is None or ret <= 0:
        return "최근 20일 흐름이 약해서 지금은 담지 않아요."
    return "더 강하게 오르는 종목이 있어 이번엔 담지 않아요."


class DemoCandleAdvisor:
    """규칙으로 만든 캔들분석 예시 판단. 데모 시세(seed-demo)에서만 쓴다."""

    @property
    def source(self) -> str:
        return SOURCE

    def advise(self, request: CandleRequest) -> AdviceResult:
        returns = {b.label: _short_return(b) for b in request.symbols}
        rising = sorted(
            (
                b
                for b in request.symbols
                if not _leveraged(b) and _above_average(b) and (returns[b.label] or 0) > 0
            ),
            key=lambda b: returns[b.label] or 0,
            reverse=True,
        )[:CANDLE_PICKS]
        weights = {b.label: 0 for b in request.symbols}
        previous = dict(request.previous or {})
        kept = bool(previous) and {s for s, w in previous.items() if w and s != CASH} == {
            b.label for b in rising
        }
        if kept:
            weights |= {s: w for s, w in previous.items() if s != CASH}
        elif rising:
            share, extra = divmod(80, len(rising))
            for i, b in enumerate(rising):
                weights[b.label] = min(share + (1 if i < extra else 0), MAX_WEIGHT)
        cash = 100 - sum(weights.values())
        reasons = {
            b.label: _candle_reason(b, weights[b.label], returns[b.label]) for b in request.symbols
        }
        reasons[CASH] = "갑자기 떨어질 때와 다음 달 사기를 위해 남겨 둬요."
        basis = _chart_basis(request, rising, returns)
        advice = Advice(
            {**weights, CASH: cash},
            reasons,
            _candle_summary(request, rising, returns, kept, cash),
            decision=_decision(kept, [f"종목 {b.label}" for b in rising], cash),
            basis=basis,
        )
        return AdviceResult(
            advice, AdviceUsage("demo-rules", 0, 0, 0, Decimal(0)), CANDLE_PROMPT_VERSION
        )


def _candle_summary(
    request: CandleRequest,
    rising: list[CandleBrief],
    returns: dict[str, Decimal | None],
    kept: bool,
    cash: int,
) -> str:
    """실제 캔들분석 봇처럼: 전체 차트 모양 → 강한 종목 → 약한 종목 → 한 일 (차트만)."""
    plain = [b for b in request.symbols if not _leveraged(b)]
    above = [b for b in plain if _above_average(b)]
    share = len(above) / len(plain) if plain else 0
    if share >= 0.6:
        out = ["대부분 종목이 90일 평균 위에서 오름 흐름을 이어 가고 있습니다."]
    elif share <= 0.3:
        out = ["대부분 종목이 90일 평균 아래로 내려와 쉬어 가는 모습입니다."]
    else:
        out = ["종목마다 차트 흐름이 엇갈립니다."]
    if rising:
        names = "·".join(f"종목 {b.label}" for b in rising)
        gains = ", ".join(f"{returns[b.label] or 0:+.1f}%" for b in rising)
        out.append(f"그중 {subj(names)} 최근 20일 동안 가장 힘 있게 올랐습니다 ({gains}).")
    weak = [b for b in plain if b not in above]
    if weak and share > 0.3:
        names = "·".join(f"종목 {b.label}" for b in weak[:3])
        out.append(f"반면 {subj(names)} 평균 아래로 내려와 약한 흐름이 뚜렷합니다.")
    if kept:
        out.append("지난 판단을 바꿀 분명한 이유가 없어 비중을 그대로 유지합니다.")
    elif rising:
        names = ", ".join(f"종목 {b.label}" for b in rising)
        out.append(f"{obj(names)} 담고 현금 {cash}%를 남깁니다.")
    else:
        out.append("오르는 차트가 없어 모두 현금으로 둡니다.")
    return " ".join(out)


def _chart_basis(
    request: CandleRequest, rising: list[CandleBrief], returns: dict[str, Decimal | None]
) -> tuple[Basis, ...]:
    """차트에서 본 것만: 오르는 종목을 한 줄로 묶고, 약해진 종목을 한 줄."""
    out = []
    if rising:
        names = "·".join(f"종목 {b.label}" for b in rising)
        gains = ", ".join(f"{returns[b.label] or 0:+.1f}%" for b in rising)
        out.append(f"{subj(names)} 최근 20일 동안 오르며 90일 평균 위에 있어요 ({gains}).")
    weak = [b for b in request.symbols if not _leveraged(b) and not _above_average(b)]
    if weak:
        names = "·".join(f"종목 {b.label}" for b in weak[:3])
        out.append(f"{subj(names)} 90일 평균 아래로 내려와 오르는 힘이 약해요.")
    if not out:
        out.append("뚜렷하게 오르거나 내리는 차트가 없어요.")
    return tuple(Basis(t) for t in out)
