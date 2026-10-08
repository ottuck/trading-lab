"""AI 봇 (마일스톤 4 A2): 목표 비중 → 팔기·사기, 매일 판단 1번, 기록된 판단으로 재생 = DRY RUN."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from quant_lab.application.ai_judge import AiConfig
from quant_lab.application.ai_view import ai_compare
from quant_lab.application.replay import replay_bot
from quant_lab.domain.advisor import (
    Advice,
    AdviceRequest,
    AdviceResult,
    AdviceUsage,
    AdvisorError,
)
from quant_lab.domain.backtest import run_backtest
from quant_lab.domain.bot import BotState
from quant_lab.domain.candles import CandleRequest
from quant_lab.domain.portfolio import CostModel, Portfolio, RiskLimits
from quant_lab.domain.strategy import AiCandle, AiJudge
from quant_lab.domain.trading import Action, rebalance
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot
from quant_lab.persistence.models import AiJudgmentRow, EventRow, SimOrderRow
from tests.fakes import WeekdayCalendar, make_bars

COSTS = CostModel()
QQQ = make_bars("QQQ", [100 + (i % 9) * 2 - (i % 4) * 3 for i in range(45)])
VOO = make_bars("VOO", [80 + (i % 7) * 3 - (i % 5) * 2 for i in range(45)])
HISTORIES = {"QQQ": QQQ[:30], "VOO": VOO[:30]}


def test_rebalance_sells_first_and_ignores_small_gaps() -> None:
    pf = Portfolio(cash=Decimal(10_000))
    pf.buy("QQQ", 6000 / QQQ[29].close, QQQ[29].close, Decimal(0))  # QQQ 60%, 현금 40%
    closes = {s: h[-1].close for s, h in HISTORIES.items()}
    equity = pf.equity(closes)

    records = rebalance({"QQQ": 50, "VOO": 40}, HISTORIES, pf, COSTS, RiskLimits())
    sell, buy = records
    assert (sell.symbol, sell.action, buy.symbol, buy.action) == (
        "QQQ",
        Action.SELL,
        "VOO",
        Action.BUY,
    )
    assert sell.budget == pf.qty("QQQ") * closes["QQQ"] - equity / 2  # 팔 금액 (일부만)
    assert buy.budget == equity * 40 / 100  # 판 돈과 현금으로 살 수 있는 만큼

    # 목표와 1%p 차이는 그대로 둔다. 목표 0이면 남김없이 판다. 판단이 없으면 모두 그대로
    now_qqq = int(pf.qty("QQQ") * closes["QQQ"] / equity * 100)
    small = rebalance({"QQQ": now_qqq + 1}, HISTORIES, pf, COSTS, RiskLimits())
    assert [r.action for r in small if r.symbol == "QQQ"] == [Action.HOLD]
    out = rebalance({"VOO": 100}, HISTORIES, pf, COSTS, RiskLimits())
    assert out[0].symbol == "QQQ" and out[0].action is Action.SELL and out[0].budget is None
    none = rebalance(None, HISTORIES, pf, COSTS, RiskLimits(), missing="그대로")
    assert {r.action for r in none} == {Action.HOLD} and none[0].reason == "그대로"


class CyclingAdvisor:
    """날마다 비중을 바꾸고, 세 번째 날은 실패하는 가짜 AI."""

    source = "fake"

    def __init__(self) -> None:
        self.calls: list[AdviceRequest] = []

    def advise(self, request: AdviceRequest) -> AdviceResult:
        self.calls.append(request)
        n = len(self.calls)
        if n == 3:
            raise AdvisorError("네트워크", AdviceUsage("m", 10, 1, 0, Decimal("0.02")))
        weights = [
            {"QQQ": 70, "VOO": 20, "CASH": 10},
            {"QQQ": 20, "VOO": 60, "CASH": 20},
            {"QQQ": 0, "VOO": 50, "CASH": 50},
        ][n % 3]
        usage = AdviceUsage("m", 10, 1, 1, Decimal("0.05"))
        return AdviceResult(Advice(weights, {"QQQ": "이유"}, "요약"), usage, "v")


def test_ai_bot_dry_run_matches_replay_of_recorded_judgments(
    engine: Engine, session: Session
) -> None:
    upsert_daily_bars(session, QQQ + VOO, "test", datetime(2026, 1, 1, tzinfo=UTC))
    strategy = AiJudge(deposit=500, day=1)
    weights = {"QQQ": 50, "VOO": 50}
    bot = create_bot(
        session,
        name="ai",
        symbol="QQQ",
        strategy="ai_judge",
        params=strategy.params,
        initial_cash=Decimal(1000),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
        weights=weights,
    )
    bot.state = BotState.RUNNING
    session.commit()
    advisor = CyclingAdvisor()
    make_session: Callable[[], Session] = sessionmaker(engine)
    start, end = QQQ[strategy.warmup - 1].session_date, QQQ[-1].session_date
    ai = AiConfig(advisor, Decimal(15))
    outcomes = replay_bot(make_session, bot.id, WeekdayCalendar(), start, end, ai=ai)
    # 같은 날을 다시 평가해도 AI는 다시 부르지 않는다
    replay_bot(make_session, bot.id, WeekdayCalendar(), end, end, ai=ai)

    rows = list(session.scalars(select(AiJudgmentRow).order_by(AiJudgmentRow.session_date)))
    assert len(advisor.calls) == len(outcomes) == len(rows)
    assert [r.status for r in rows[:4]] == ["OK", "OK", "FAILED", "OK"]
    assert rows[2].cost == Decimal("0.02")  # 돈이 든 실패도 비용을 남긴다
    assert advisor.calls[1].previous == rows[0].weights  # 지난 판단을 함께 넘긴다
    warn = session.scalars(select(EventRow).where(EventRow.kind == "ai_judgment")).all()
    assert len(warn) == 1 and warn[0].level == "WARN"

    # 원칙 3·9: 기록된 판단으로 다시 돌린 결과가 DRY RUN 체결과 같다
    judgments = {r.session_date: (r.weights if r.status == "OK" else None) for r in rows}
    expected = run_backtest(
        {"QQQ": QQQ, "VOO": VOO},
        strategy,
        Decimal(1000),
        COSTS,
        weights=weights,
        judgments=judgments,
    )
    filled = session.scalars(
        select(SimOrderRow).where(SimOrderRow.status == "FILLED").order_by(SimOrderRow.id)
    )
    got = [(o.symbol, o.side, o.signal_date, o.qty, o.price) for o in filled]
    assert {side for _, side, *_ in got} == {"BUY", "SELL"}
    assert got == [(f.symbol, f.side, f.signal_date, f.qty, f.price) for f in expected.fills]

    # 화면 비교(A3)의 AI 봇 값도 같은 재생이다. 나 카피 봇이 없으면 매달 그냥 사기와만 비교한다
    compare = ai_compare(session, bot.id)
    assert [w.key for w in compare.worlds] == ["me", "dca"]
    assert compare.worlds[0].final_equity == expected.metrics.final_equity


def test_ai_bot_stops_calling_over_monthly_budget(engine: Engine, session: Session) -> None:
    upsert_daily_bars(session, QQQ + VOO, "test", datetime(2026, 1, 1, tzinfo=UTC))
    bot = create_bot(
        session,
        name="ai",
        symbol="QQQ",
        strategy="ai_judge",
        params=AiJudge(deposit=500, day=1).params,
        initial_cash=Decimal(1000),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
        weights={"QQQ": 50, "VOO": 50},
    )
    bot.state = BotState.RUNNING
    session.commit()
    advisor = CyclingAdvisor()
    days = (QQQ[25].session_date, QQQ[30].session_date)
    replay_bot(
        sessionmaker(engine), bot.id, WeekdayCalendar(), *days, ai=AiConfig(advisor, Decimal("0.1"))
    )

    statuses = list(
        session.scalars(select(AiJudgmentRow.status).order_by(AiJudgmentRow.session_date))
    )
    assert len(advisor.calls) == 2  # $0.05 두 번이면 상한 $0.1
    assert statuses[2:] == ["OVER_BUDGET"] * (len(statuses) - 2)
    notices = session.scalars(
        select(EventRow.level).where(EventRow.kind == "ai_judgment").order_by(EventRow.id)
    ).all()
    assert notices[0] == "WARN" and set(notices[1:]) == {"INFO"}  # 상한은 한 번만 알린다


class LabelAdvisor:
    """익명 표만 보는 가짜 캔들 AI: 날마다 첫 글자와 둘째 글자에 번갈아 많이 담는다."""

    source = "fake"

    def __init__(self) -> None:
        self.calls: list[CandleRequest] = []

    def advise(self, request: CandleRequest) -> AdviceResult:
        self.calls.append(request)
        first, second = (b.label for b in request.symbols)
        heavy, light = (first, second) if len(self.calls) % 2 else (second, first)
        weights = {heavy: 60, light: 20, "CASH": 20}
        reasons = {heavy: f"종목 {light}보다 강해요", light: "약해요"}
        usage = AdviceUsage("m", 10, 1, 0, Decimal("0.01"))
        return AdviceResult(Advice(weights, reasons, f"종목 {heavy}가 강해요"), usage, "c")


def test_candle_bot_sees_only_masked_candles_and_replays(engine: Engine, session: Session) -> None:
    upsert_daily_bars(session, QQQ + VOO, "test", datetime(2026, 1, 1, tzinfo=UTC))
    strategy = AiCandle(deposit=500, day=1)
    weights = {"QQQ": 50, "VOO": 50}
    bot = create_bot(
        session,
        name="candle",
        symbol="QQQ",
        strategy="ai_candle",
        params=strategy.params,
        initial_cash=Decimal(1000),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
        weights=weights,
    )
    bot.state = BotState.RUNNING
    session.commit()
    advisor = LabelAdvisor()
    start, end = QQQ[strategy.warmup - 1].session_date, QQQ[-1].session_date
    # 시장분석 AI 봇의 상한(0)은 캔들분석 AI 봇을 막지 않는다 (전략마다 따로 센다)
    ai = AiConfig(None, Decimal(0), advisor, Decimal(15))
    replay_bot(sessionmaker(engine), bot.id, WeekdayCalendar(), start, end, ai=ai)

    rows = list(session.scalars(select(AiJudgmentRow).order_by(AiJudgmentRow.session_date)))
    assert len(rows) == len(advisor.calls) > 2
    assert {r.status for r in rows} == {"OK"} and {r.strategy for r in rows} == {"ai_candle"}
    assert all("QQQ" not in str(c.as_dict()) for c in advisor.calls)  # 이름은 넘기지 않는다
    assert set(rows[0].weights or {}) == {"QQQ", "VOO", "CASH"}  # 기록은 종목으로 되돌린 판단
    assert (rows[0].summary or "").removesuffix("가 강해요") in ("QQQ", "VOO")

    judgments = {r.session_date: r.weights for r in rows}
    expected = run_backtest(
        {"QQQ": QQQ, "VOO": VOO},
        strategy,
        Decimal(1000),
        COSTS,
        weights=weights,
        judgments=judgments,
    )
    filled = session.scalars(
        select(SimOrderRow).where(SimOrderRow.status == "FILLED").order_by(SimOrderRow.id)
    )
    got = [(o.symbol, o.side, o.signal_date, o.qty, o.price) for o in filled]
    assert got and got == [
        (f.symbol, f.side, f.signal_date, f.qty, f.price) for f in expected.fills
    ]

    # 나중에 시작한 시장분석 AI 봇의 비교에는 캔들 봇이 그날 같은 돈으로 시작했다면이 함께 나온다.
    # 먼저 시작한 캔들 봇의 비교에는 (그 앞 날 판단이 없는) 시장분석 AI 봇이 나오지 않는다
    market = create_bot(
        session,
        name="market",
        symbol="QQQ",
        strategy="ai_judge",
        params=AiJudge(deposit=500, day=1).params,
        initial_cash=Decimal(1000),
        costs=COSTS,
        limits=RiskLimits(),
        now=datetime.now(UTC),
        weights=weights,
    )
    market.state = BotState.RUNNING
    session.commit()
    later = QQQ[strategy.warmup + 4].session_date
    ai = AiConfig(CyclingAdvisor(), Decimal(15))
    replay_bot(sessionmaker(engine), market.id, WeekdayCalendar(), later, end, ai=ai)
    seen = ai_compare(session, market.id)
    assert [w.key for w in seen.worlds] == ["me", f"ai-{bot.id}", "dca"]
    assert seen.worlds[1].title == "candle" and seen.worlds[1].start == seen.worlds[0].start
    assert [w.key for w in ai_compare(session, bot.id).worlds] == ["me", "dca"]
