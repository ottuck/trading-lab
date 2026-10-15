"""포트폴리오 데모의 예시 AI 판단 (데모에는 AI 키가 없다, project.md 11-1절).

실제 AI가 아니라 정해진 규칙으로 domain/advisor.py 규약에 맞는 판단을 만든다. 같은 입력이면
늘 같은 판단이고 비용은 0이다. 화면은 "예시 판단"이라고 알린다.

규칙: 레버리지가 아닌 종목 중 200일 평균 위에 있고 3개월 수익이 플러스인 종목을 3개월 수익이 큰
순서로 5개까지 담는다. 변동성이 작을수록 많이 담되 한 종목은 30%까지, 현금은 20% 이상 남긴다
(담을 종목이 없으면 모두 현금).
담을 종목이 지난 판단과 같으면 지난 비중을 그대로 둔다 (실제 AI 지침처럼 이유 없이 바꾸지 않음).

캔들분석 AI 봇의 예시 판단(DemoCandleAdvisor)은 실제 봇처럼 익명 캔들 표만 받는다. 레버리지가
아닌 종목 중 판단일 지수가 90일 평균 위이고 최근 20일 수익이 플러스인 종목을 20일 수익이 큰
순서로 4개까지 똑같이 나눠 담는다 (한 종목 30%까지, 현금 20% 이상, 지난 판단 유지는 같다).
"""

from decimal import ROUND_DOWN, Decimal

from trading_lab.domain.advisor import (
    CASH,
    Advice,
    AdviceRequest,
    AdviceResult,
    AdviceUsage,
    SymbolBrief,
)
from trading_lab.domain.candles import CandleBrief, CandleRequest

SOURCE = "demo"
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
        names = ", ".join(b.symbol for b in rising)
        summary = (
            "예시 판단이에요 (실제 AI가 아니라 정해진 규칙으로 만들어요). "
            + (f"오르는 흐름의 종목({names})을 담고 " if rising else "오르는 종목이 없어 ")
            + f"현금 {cash}%를 남겨요."
            + (" 지난 판단과 같아 비중을 그대로 둬요." if kept else "")
        )
        advice = Advice({**weights, CASH: cash}, reasons, summary)
        return AdviceResult(advice, AdviceUsage("demo-rules", 0, 0, 0, Decimal(0)), "demo-1")


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
        names = ", ".join(f"종목 {b.label}" for b in rising)
        summary = (
            "예시 판단이에요 (실제 AI가 아니라 정해진 규칙으로 만들어요). "
            + (f"최근 차트가 가장 강한 {names}를 담고 " if rising else "오르는 차트가 없어 ")
            + f"현금 {cash}%를 남겨요."
            + (" 지난 판단과 같아 비중을 그대로 둬요." if kept else "")
        )
        advice = Advice({**weights, CASH: cash}, reasons, summary)
        return AdviceResult(advice, AdviceUsage("demo-rules", 0, 0, 0, Decimal(0)), "demo-candle-1")
