"""AI 판단 규약 (port)과 판단에 넘기는 요약·검증 규칙 (project.md 14절).

AI는 정해 준 종목과 현금 사이의 목표 비중만 정한다. 주문·체결·한도는 엔진이 한다.
엔진은 이 모듈만 알고, 실제 AI 공급자 호출은 adapters/에서 이 형식으로 바꿔 넘긴다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Any, Protocol

from quant_lab.domain.bars import DailyBar
from quant_lab.domain.candles import CASH as CASH  # 판단 비중의 현금 키 (여기서도 쓴다)
from quant_lab.domain.candles import CandleRequest, MaskedCandles, mask, unmask_text

ONE_YEAR = 252  # 거래일
MIN_BARS = 21  # 이보다 짧은 이력의 종목은 요약하지 않는다 (상장 한 달 미만)


class AdvisorError(Exception):
    """AI 판단을 받지 못했다 (네트워크·한도·거절·형식 오류). 그날은 판단하지 않는다.

    돈이 든 뒤 실패했으면(형식 오류 등) usage에 그 비용을 담는다.
    """

    def __init__(self, message: str, usage: AdviceUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class JudgmentStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"  # 호출 실패 (네트워크·한도·거절·키 없음)
    INVALID = "INVALID"  # 답은 왔지만 형식·비중이 규칙에 맞지 않음
    OVER_BUDGET = "OVER_BUDGET"  # 이번 달 비용 상한을 넘어 부르지 않음


# --- 입력: 엔진이 계산한 요약 (시장분석 AI 봇에는 원본 일봉을 넘기지 않는다) ---


def _pct(value: Decimal) -> Decimal:
    return (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class SymbolBrief:
    """종목 하나의 판단일 종가 기준 요약. 비율 값은 % (소수 첫째 자리)."""

    symbol: str
    close: Decimal
    vs_sma200: Decimal | None  # 200일 평균 대비 (이력이 짧으면 None)
    vs_high: Decimal  # 1년(이력이 짧으면 상장 뒤) 최고 종가 대비, 0 이하
    return_1m: Decimal | None
    return_3m: Decimal | None
    return_12m: Decimal | None
    volatility: Decimal  # 최근 3개월 하루 변동의 연 환산 표준편차
    weight_now: Decimal  # 지금 봇 자산에서 차지하는 비중
    leverage: Decimal | None = None  # 레버리지 ETF 배수

    def as_dict(self) -> dict[str, Any]:
        return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in _fields(self).items()}


def _fields(obj: object) -> dict[str, Any]:
    return {name: getattr(obj, name) for name in obj.__slots__}  # type: ignore[attr-defined]


def _ret(bars: Sequence[DailyBar], days: int) -> Decimal | None:
    if len(bars) <= days:
        return None
    return _pct(bars[-1].close / bars[-1 - days].close - 1)


def brief(
    history: Sequence[DailyBar], weight_now: Decimal, leverage: Decimal | None = None
) -> SymbolBrief | None:
    """history의 마지막 봉(완료된 판단일)까지로 요약한다. 이력이 한 달보다 짧으면 None."""
    if len(history) < MIN_BARS:
        return None
    last = history[-1]
    year = history[-ONE_YEAR:]
    high = max(b.close for b in year)
    sma200 = None
    if len(history) >= 200:
        sma200 = _pct(last.close / (sum((b.close for b in history[-200:]), Decimal(0)) / 200) - 1)
    window = history[-64:]
    changes = [b.close / a.close - 1 for a, b in pairwise(window)]
    mean = sum(changes, Decimal(0)) / len(changes)
    var = sum(((c - mean) ** 2 for c in changes), Decimal(0)) / len(changes)
    volatility = _pct(var.sqrt() * Decimal(ONE_YEAR).sqrt())
    return SymbolBrief(
        symbol=last.symbol,
        close=last.close,
        vs_sma200=sma200,
        vs_high=_pct(last.close / high - 1),
        return_1m=_ret(history, 21),
        return_3m=_ret(history, 63),
        return_12m=_ret(history, ONE_YEAR),
        volatility=volatility,
        weight_now=weight_now,
        leverage=leverage,
    )


@dataclass(frozen=True, slots=True)
class AdviceRequest:
    """AI에게 넘기는 판단 입력 전부. 그대로 기록해 나중에 다시 볼 수 있다."""

    session_date: date  # 판단일 (미국 거래일, 이 날 종가까지 앎)
    symbols: tuple[SymbolBrief, ...]  # 고른 종목 (이력이 짧아 요약하지 못한 종목은 빠짐)
    equity: Decimal  # 봇 자산 (현금 + 주식, 판단일 종가)
    cash_weight: Decimal  # 지금 현금 비중 %
    contributed: Decimal  # 지금까지 넣은 돈
    monthly_deposit: Decimal  # 매달 넣는 돈
    previous: Mapping[str, int] | None = None  # 지난 판단의 목표 비중 (현금은 "CASH")
    previous_date: date | None = None
    as_of: datetime | None = None  # 판단을 부른 시각 (AI가 검색할 때 "지금"을 알게)
    # 캔들분석 AI 봇의 익명 입력 (domain/candles.py). 시장분석 AI 봇은 None
    candles: MaskedCandles | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "session_date": self.session_date.isoformat(),
            "symbols": [s.as_dict() for s in self.symbols],
            "equity": str(self.equity),
            "cash_weight": str(self.cash_weight),
            "contributed": str(self.contributed),
            "monthly_deposit": str(self.monthly_deposit),
            "previous": dict(self.previous) if self.previous is not None else None,
            "previous_date": self.previous_date.isoformat() if self.previous_date else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }
        if self.candles is not None:
            out["candles"] = self.candles.as_dict()
        return out


# --- 출력 ---


@dataclass(frozen=True, slots=True)
class Source:
    url: str
    title: str
    used: bool = False  # AI가 판단의 근거로 썼다고 밝힌 기사 (나머지는 검색 결과로 받아 보기만 함)


@dataclass(frozen=True, slots=True)
class AdviceUsage:
    """판단 한 번에 든 것. cost는 달러 (공급자 요금표로 어댑터가 계산)."""

    model: str
    input_tokens: int
    output_tokens: int
    web_searches: int
    cost: Decimal


@dataclass(frozen=True, slots=True)
class Advice:
    """AI가 낸 판단. weights는 종목별 목표 비중 %(정수)이고 현금은 CASH 키로 함께 담는다."""

    weights: Mapping[str, int]
    reasons: Mapping[str, str]  # 종목별 쉬운 말 이유 (현금 포함)
    summary: str  # 오늘의 시장 요약
    sources: tuple[Source, ...] = ()
    queries: tuple[str, ...] = ()  # AI가 검색한 말


@dataclass(frozen=True, slots=True)
class AdviceResult:
    advice: Advice
    usage: AdviceUsage
    prompt_version: str  # 지침 버전. 지침을 바꾸면 올린다


class Advisor(Protocol):
    """AI 판단 공급자. source는 저장 데이터에 남기는 출처 코드."""

    @property
    def source(self) -> str: ...

    def advise(self, request: AdviceRequest) -> AdviceResult:
        """판단을 돌려준다. 받지 못하면 AdvisorError."""
        ...


class CandleAdvisor(Protocol):
    """캔들분석 AI 판단 공급자. 익명 입력만 받고 종목은 글자("A", "B", ...)로 답한다."""

    @property
    def source(self) -> str: ...

    def advise(self, request: CandleRequest) -> AdviceResult:
        """판단을 돌려준다. 받지 못하면 AdvisorError."""
        ...


def unmask(advice: Advice, key: Mapping[str, str]) -> Advice:
    """글자로 낸 판단을 종목으로 되돌린다. 모르는 글자는 그대로 둬 check_advice에서 걸린다."""
    return Advice(
        weights={key.get(k, k): w for k, w in advice.weights.items()},
        reasons={key.get(k, k): unmask_text(r, key) for k, r in advice.reasons.items()},
        summary=unmask_text(advice.summary, key),
        sources=advice.sources,
        queries=advice.queries,
    )


@dataclass(frozen=True)
class Unmasking:
    """캔들 공급자를 Advisor 규약으로 감싼다: 익명 입력만 넘기고 답을 종목으로 되돌린다."""

    inner: CandleAdvisor

    @property
    def source(self) -> str:
        return self.inner.source

    def advise(self, request: AdviceRequest) -> AdviceResult:
        if request.candles is None:
            raise AdvisorError("캔들 입력이 없음")
        result = self.inner.advise(request.candles.request)
        advice = unmask(result.advice, request.candles.key)
        return AdviceResult(advice, result.usage, result.prompt_version)


def check_advice(advice: Advice, symbols: Sequence[str]) -> str | None:
    """정해 준 종목·현금만 있고 비중이 0~100 정수이며 합이 100인지. 맞으면 None, 아니면 이유."""
    allowed = {*symbols, CASH}
    unknown = set(advice.weights) - allowed
    if unknown:
        return f"정해 주지 않은 종목: {', '.join(sorted(unknown))}"
    if any(not 0 <= w <= 100 for w in advice.weights.values()):
        return "비중은 0~100이어야 함"
    total = sum(advice.weights.values())
    if total != 100:
        return f"비중 합이 100이 아님 ({total})"
    return None


@dataclass(frozen=True, slots=True)
class Judgment:
    """기록할 판단 1건 (ai_judgments 1행). OK가 아니면 advice가 없다."""

    session_date: date
    status: JudgmentStatus
    request: AdviceRequest | None
    advice: Advice | None = None
    usage: AdviceUsage | None = None
    prompt_version: str | None = None
    source: str | None = None
    error: str | None = None


def make_request(
    histories: Mapping[str, Sequence[DailyBar]],
    cash: Decimal,
    qtys: Mapping[str, Decimal],
    contributed: Decimal,
    monthly_deposit: Decimal,
    leverage: Mapping[str, Decimal | None] | None = None,
    previous: Mapping[str, int] | None = None,
    previous_date: date | None = None,
    as_of: datetime | None = None,
    candles: bool = False,
) -> AdviceRequest:
    """판단일(모든 종목의 마지막 봉) 종가로 봇 상태를 요약한다. 이력이 짧은 종목은 빠진다.

    candles면 같은 종목으로 캔들분석 AI 봇의 익명 입력도 함께 만든다.
    """
    closes = {s: h[-1].close for s, h in histories.items()}
    equity = cash + sum((qtys.get(s, Decimal(0)) * c for s, c in closes.items()), Decimal(0))
    briefs = []
    for symbol, history in histories.items():
        weight = qtys.get(symbol, Decimal(0)) * closes[symbol] / equity if equity else Decimal(0)
        item = brief(history, _pct(weight), (leverage or {}).get(symbol))
        if item is not None:
            briefs.append(item)
    session_date = max(h[-1].session_date for h in histories.values())
    cash_weight = _pct(cash / equity) if equity else Decimal(100)
    masked = None
    if candles:
        masked = mask(
            {b.symbol: histories[b.symbol] for b in briefs},
            {b.symbol: b.weight_now for b in briefs},
            {b.symbol: b.leverage for b in briefs},
            cash_weight,
            previous,
            session_date,
        )
    return AdviceRequest(
        session_date=session_date,
        symbols=tuple(briefs),
        equity=equity.quantize(Decimal("0.01")),
        cash_weight=cash_weight,
        contributed=contributed,
        monthly_deposit=monthly_deposit,
        previous=previous,
        previous_date=previous_date,
        as_of=as_of,
        candles=masked,
    )
