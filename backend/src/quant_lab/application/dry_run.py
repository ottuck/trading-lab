"""정기 DRY RUN 평가 1회 (project.md 4절 'Worker 평가 1회의 흐름').

명령 확인 → 장 운영 판정 → 완료 봉 수집·검증 → 이전 대기 주문 체결(T+1 시가)
→ 전략 판단 → 위험 검사 → 모의 주문 생성 → 상태·다음 평가 시각 저장
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_lab.application.ai_judge import AiConfig, judge_bot
from quant_lab.application.bar_sync import DEFAULT_SETTLE
from quant_lab.application.market import MarketData
from quant_lab.application.weekly import is_week_end, weekly_summary
from quant_lab.domain.advisor import AdviceRequest, JudgmentStatus, make_request
from quant_lab.domain.bars import (
    DailyBar,
    TradingCalendar,
    check_daily_bars,
    is_completed,
    outlier_limit,
)
from quant_lab.domain.bot import BotState
from quant_lab.domain.broker import BrokerAccessError, BrokerError
from quant_lab.domain.events import (
    AiDecisionData,
    BalanceSummary,
    DecisionData,
    DecisionRepeatData,
    DepositData,
    ErrorReason,
    EventKind,
    FillData,
    MissedSessionsData,
    RunData,
    SkipReason,
)
from quant_lab.domain.feedback import CALLS as FEEDBACK_CALLS
from quant_lab.domain.portfolio import Portfolio, money
from quant_lab.domain.strategy import (
    STRATEGIES,
    Strategy,
    is_ai,
    is_candle,
    min_bars,
    month_key,
)
from quant_lab.domain.trading import (
    Action,
    DecisionRecord,
    Fill,
    decide_basket,
    execute,
    rebalance,
)
from quant_lab.persistence.ai_judgments import judgment_for, recent_ok
from quant_lab.persistence.backtests import to_jsonable
from quant_lab.persistence.bars import load_daily_bars
from quant_lab.persistence.bots import (
    active_weights,
    add_event,
    bot_costs,
    bot_limits,
    bot_weights,
    deposited_month,
    get_bot,
    load_account,
    pending_orders,
    save_account,
    set_bot_state,
)
from quant_lab.persistence.market_info import leverage_of
from quant_lab.persistence.models import BotDepositRow, BotRow, DecisionRow, RunRow, SimOrderRow

MODE = "DRY_RUN"
RETRY_AFTER = timedelta(minutes=15)

log = logging.getLogger(__name__)


class RunStatus(StrEnum):
    OK = "OK"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


class Trigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class EvaluationOutcome:
    run_id: uuid.UUID
    status: RunStatus
    session_date: date | None
    detail: str
    decisions: tuple[DecisionRecord, ...] = ()  # 종목별 판단 (여러 종목 봇은 여러 개)
    fills: tuple[Fill, ...] = ()
    reason: str | None = None  # SKIPPED·ERROR의 이유 코드 (domain/events.py)


class _Skip(Exception):
    """신규 주문 없이 이번 평가를 건너뛴다. 잠시 뒤 다시 시도한다."""

    def __init__(self, reason: SkipReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class _NeedJudgment(Exception):
    """AI 봇의 그날 판단이 아직 없다. request는 그날 체결·입금까지 반영한 봇 상태."""

    def __init__(self, request: AdviceRequest) -> None:
        super().__init__("AI 판단이 필요합니다")
        self.request = request


def build_strategy(bot: BotRow) -> Strategy:
    return STRATEGIES[bot.strategy](**bot.params)


def latest_completed_session(
    calendar: TradingCalendar, now: datetime, settle: timedelta = DEFAULT_SETTLE
) -> date:
    today = now.date()
    sessions = calendar.sessions(today - timedelta(days=14), today)
    done = [s for s in sessions if is_completed(s, calendar, now, settle)]
    if not done:
        raise _Skip(SkipReason.NO_RECENT_SESSION, "최근 2주 안에 완료된 거래일이 없습니다")
    return done[-1]


def next_evaluation_time(
    calendar: TradingCalendar, session_date: date, settle: timedelta = DEFAULT_SETTLE
) -> datetime:
    upcoming = calendar.sessions(
        session_date + timedelta(days=1), session_date + timedelta(days=14)
    )
    return calendar.session_close(upcoming[0]) + settle


def evaluate_bot(
    session: Session,
    bot_id: int,
    *,
    market: MarketData,
    calendar: TradingCalendar,
    now: datetime,
    trigger: Trigger,
    ai: AiConfig | None = None,
) -> EvaluationOutcome:
    if session.get(BotRow, bot_id) is None:
        # 평가 대상을 고른 뒤 화면에서 봇이 지워진 경우. 실행 기록도 남기지 않는다.
        return EvaluationOutcome(uuid.uuid4(), RunStatus.SKIPPED, None, f"봇 {bot_id}가 없습니다")
    run = RunRow(id=uuid.uuid4(), bot_id=bot_id, trigger=trigger, started_at=now, status="RUNNING")
    session.add(run)
    session.commit()
    run_id = run.id

    try:
        try:
            outcome = _evaluate(session, bot_id, run_id, market, calendar, now)
        except _NeedJudgment as need:
            # AI 봇의 그날 판단이 없다: 봇 행을 잠근 채 AI를 기다리지 않게 되돌리고,
            # 판단을 받아 기록한 뒤 처음부터 다시 평가한다 (이번엔 기록된 판단을 쓴다).
            session.rollback()
            judge_bot(session, bot_id, need.request, ai, now)
            outcome = _evaluate(session, bot_id, run_id, market, calendar, now)
    except _Skip as skip:
        session.rollback()
        outcome = EvaluationOutcome(run_id, RunStatus.SKIPPED, None, str(skip), reason=skip.reason)
        _finish(session, bot_id, outcome, now, level="WARN", retry=True)
    except BrokerAccessError as exc:
        # 허용 IP·토큰 경합은 기다려도 풀리지 않는다. 사람이 확인할 때까지 멈춘다.
        session.rollback()
        outcome = EvaluationOutcome(
            run_id,
            RunStatus.ERROR,
            None,
            f"증권사 인증·권한 오류: {exc}",
            reason=ErrorReason.BROKER_ACCESS,
        )
        _finish(session, bot_id, outcome, now, level="ERROR", to_error=True)
    except BrokerError as exc:
        session.rollback()
        outcome = EvaluationOutcome(
            run_id,
            RunStatus.SKIPPED,
            None,
            f"증권사 호출 실패: {exc}",
            reason=SkipReason.BROKER_UNAVAILABLE,
        )
        _finish(session, bot_id, outcome, now, level="WARN", retry=True)
    except Exception as exc:
        session.rollback()
        log.exception("평가 실패 bot=%s", bot_id)
        outcome = EvaluationOutcome(
            run_id,
            RunStatus.ERROR,
            None,
            f"예상하지 못한 오류: {exc!r}",
            reason=ErrorReason.UNEXPECTED,
        )
        _finish(session, bot_id, outcome, now, level="ERROR", to_error=True)
    return outcome


def _finish(
    session: Session,
    bot_id: int,
    outcome: EvaluationOutcome,
    now: datetime,
    *,
    level: str,
    retry: bool = False,
    to_error: bool = False,
) -> None:
    run = session.get_one(RunRow, outcome.run_id)
    if level == "WARN" and _same_as_previous_run(session, bot_id, outcome):
        # 같은 이유로 15분마다 재시도할 때 알림이 반복되지 않게, 두 번째부터는 INFO로 남긴다.
        level = "INFO"
    run.status = outcome.status
    run.detail = outcome.detail
    run.session_date = outcome.session_date
    run.finished_at = now
    bot = get_bot(session, bot_id)
    if bot is not None:
        if to_error:
            set_bot_state(session, bot, BotState.ERROR, outcome.detail, now)
        elif retry:
            bot.next_evaluation_at = now + RETRY_AFTER
    data: RunData = {"reason": outcome.reason or ""}
    add_event(
        session,
        now,
        level,
        EventKind.RUN_SKIPPED if outcome.status is RunStatus.SKIPPED else EventKind.RUN_ERROR,
        outcome.detail,
        bot_id=bot_id,
        run_id=outcome.run_id,
        data=data,
    )
    session.commit()


def _same_as_previous_run(session: Session, bot_id: int, outcome: EvaluationOutcome) -> bool:
    previous = session.scalars(
        select(RunRow)
        .where(
            RunRow.bot_id == bot_id, RunRow.id != outcome.run_id, RunRow.finished_at.is_not(None)
        )
        .order_by(RunRow.started_at.desc())
        .limit(1)
    ).first()
    return (
        previous is not None
        and previous.status == outcome.status
        and previous.detail == outcome.detail
    )


def _evaluate(
    session: Session,
    bot_id: int,
    run_id: uuid.UUID,
    market: MarketData,
    calendar: TradingCalendar,
    now: datetime,
) -> EvaluationOutcome:
    bot = get_bot(session, bot_id, for_update=True)
    if bot is None:
        raise _Skip(SkipReason.BOT_MISSING, f"봇 {bot_id}가 없습니다")
    strategy = build_strategy(bot)
    costs, limits = bot_costs(bot), bot_limits(bot)

    # 1) 장 운영 판정
    target = latest_completed_session(calendar, now)
    confirmed = market.confirm_session(target)
    if confirmed is False:
        raise _Skip(
            SkipReason.CALENDAR_MISMATCH, f"{target}: XNYS는 거래일이지만 증권사 달력은 아닙니다"
        )

    # 2) 완료 봉 수집·검증 (모든 종목). 한 종목이라도 그날 봉이 없거나 문제가 있으면 전체를 미룬다
    #    (원칙 5: 현금을 함께 쓰므로 일부 종목만 먼저 판단하면 백테스트와 순서가 달라진다).
    #    종목을 바꾸며 뺀(비율 0) 보유 종목도 평가에 쓰므로 함께 확인하고, 판단은 하지 않는다.
    # 동기화 결과의 품질 문제는 판단에 쓰는 구간(아래 window)만 막는다.
    # 전체 이력에 섞인 오래된 이상치 때문에 봇이 영원히 멈추지 않게 한다.
    weights = bot_weights(bot)
    series: dict[str, list[DailyBar]] = {}
    for symbol in weights:
        who = f"{symbol} " if len(weights) > 1 else ""
        market.refresh(session, symbol, now)
        bars = load_daily_bars(session, symbol, end=target)
        if not bars or bars[-1].session_date != target:
            last = bars[-1].session_date if bars else None
            raise _Skip(
                SkipReason.DATA_NOT_READY, f"{who}{target} 일봉이 아직 없습니다 (마지막 {last})"
            )
        window = bars[-(strategy.warmup + 2) :]
        issues = check_daily_bars(window, calendar, outlier_limit(leverage_of(session, symbol)))
        if issues:
            raise _Skip(
                SkipReason.BAD_BARS,
                f"{who}판단 구간 일봉 문제: {issues[0].kind} {issues[0].session_date}",
            )
        series[symbol] = bars

    # 3) 이전 대기 주문(종목별)을 T+1 시가로 체결
    pf = load_account(session, bot.id)
    fills: list[Fill] = []
    for order in pending_orders(session, bot.id):
        if order.signal_date >= target:
            continue
        bars = series.get(order.symbol) or load_daily_bars(session, order.symbol, end=target)
        fill_bar = next(b for b in bars if b.session_date > order.signal_date)
        intent = DecisionRecord(
            order.signal_date,
            Action(order.side),
            True,
            False,
            "",
            {},
            budget=order.budget,
            symbol=order.symbol,
        )
        fill = execute(pf, intent, fill_bar, costs, limits)
        order.fill_date = fill_bar.session_date
        if fill is None:
            order.status = "UNFILLED"
            order.note = "체결 시점 현금·위험 한도로 살 수 있는 수량이 없음"
        else:
            order.status = "FILLED"
            order.qty, order.price, order.commission = fill.qty, fill.price, fill.commission
            order.realized_pnl = fill.realized_pnl
            fills.append(fill)
    session.flush()
    closes = {s: b[-1].close for s, b in series.items()}

    # 4) 이미 판단한 날이면 아무것도 하지 않는다 (수동 실행 반복 등)
    existing = session.scalars(
        select(DecisionRow).where(
            DecisionRow.bot_id == bot.id,
            DecisionRow.session_date == target,
            DecisionRow.mode == MODE,
        )
    ).first()
    if existing is not None:
        save_account(session, bot.id, pf, now)
        outcome = EvaluationOutcome(
            run_id, RunStatus.OK, target, f"{target} 판단은 이미 있음", fills=tuple(fills)
        )
        return _commit_ok(session, bot, outcome, calendar, now, _summary(bot, pf, closes))

    # Worker가 멈춰 있던 동안의 거래일은 소급 판단하지 않고 기록만 남긴다.
    last_decided = session.scalar(
        select(func.max(DecisionRow.session_date)).where(
            DecisionRow.bot_id == bot.id, DecisionRow.mode == MODE
        )
    )
    if last_decided is not None and last_decided < target - timedelta(days=1):
        missed = calendar.sessions(last_decided + timedelta(days=1), target - timedelta(days=1))
        if missed:
            add_event(
                session,
                now,
                "WARN",
                EventKind.MISSED_SESSIONS,
                f"판단 누락 {len(missed)}일: {missed[0]} ~ {missed[-1]}",
                bot_id=bot.id,
                run_id=run_id,
                data=MissedSessionsData(
                    count=len(missed), first=missed[0].isoformat(), last=missed[-1].isoformat()
                ),
            )

    # 5) 정기 입금(모으기 전략): 이번 달 입금이 아직 없고 입금일이 지났으면 오늘 넣는다.
    #    백테스트와 같은 규칙이다 (domain/strategy.py DepositPlan). 한 달 한 번은 DB PK가 보장한다.
    deposit = Decimal(0)
    plan = strategy.deposit_plan
    last_month = deposited_month(session, bot.id, target)
    if plan.due(target, last_month):
        deposit = plan.amount
        pf.deposit(deposit)
        session.add(
            BotDepositRow(
                bot_id=bot.id,
                month=month_key(target),
                session_date=target,
                amount=deposit,
                created_at=now,
            )
        )
        add_event(
            session,
            now,
            "INFO",
            EventKind.DEPOSIT,
            f"{target} 입금 ${deposit}",
            bot_id=bot.id,
            run_id=run_id,
            data=DepositData(
                symbol=bot.symbol, amount=str(deposit), contributed=str(pf.contributed)
            ),
        )

    # 6) 전략 판단·위험 검사·모의 주문 (종목별, 비율 순서대로)
    # 첫 판단(시작·처음부터 다시 시작)은 시작 금액도 새로 들어온 돈으로 본다 (백테스트와 같음).
    fresh = deposit + (bot.initial_cash if last_decided is None else Decimal(0))
    if is_ai(strategy):
        decisions = _ai_decisions(session, bot, strategy, series, pf, now)
    else:
        active = active_weights(bot)
        histories = {s: series[s] for s in active}
        decisions = decide_basket(strategy, histories, active, pf, costs, limits, fresh)
    if not decisions:
        raise _Skip(SkipReason.NOT_ENOUGH_BARS, f"봉이 부족합니다 (필요 {min_bars(strategy)}개)")
    snapshot = {
        "name": bot.strategy,
        "params": bot.params,
        "symbols": bot.symbols,
        "risk": bot.risk,
        "commission_rate": str(costs.commission_rate),
        "slippage_bps": str(costs.slippage_bps),
    }
    try:
        for decision in decisions:
            row = DecisionRow(
                bot_id=bot.id,
                symbol=decision.symbol,
                session_date=target,
                mode=MODE,
                run_id=run_id,
                strategy=snapshot,
                action=decision.action,
                target_long=decision.target_long,
                holding=decision.holding,
                reason=decision.reason,
                indicators=to_jsonable(decision.indicators),
                blocked=decision.blocked,
                created_at=now,
            )
            session.add(row)
            session.flush()
            if decision.action is not Action.HOLD:
                session.add(
                    SimOrderRow(
                        bot_id=bot.id,
                        symbol=decision.symbol,
                        decision_id=row.id,
                        side=decision.action,
                        status="PENDING",
                        signal_date=target,
                        created_at=now,
                        budget=decision.budget,
                    )
                )
                session.flush()
    except IntegrityError as exc:
        # 다른 Worker가 같은 봉을 먼저 판단했다. 이 실행의 변경은 모두 버린다.
        raise _Skip(SkipReason.DUPLICATE, f"{target} 판단 중복 차단 (DB 유일 제약)") from exc

    save_account(session, bot.id, pf, now)
    if len(decisions) == 1:
        d = decisions[0]
        detail = f"{target} {d.action}: {d.reason}"
        if d.blocked:
            detail += f" (차단: {d.blocked})"
    else:
        detail = f"{target} " + ", ".join(f"{d.symbol} {d.action}" for d in decisions)
    outcome = EvaluationOutcome(
        run_id, RunStatus.OK, target, detail, decisions=tuple(decisions), fills=tuple(fills)
    )
    return _commit_ok(session, bot, outcome, calendar, now, _summary(bot, pf, closes))


_NO_JUDGMENT = {
    JudgmentStatus.OVER_BUDGET: "이번 달 AI 비용 상한을 넘어 오늘은 지금 그대로 둬요",
}


def _ai_decisions(
    session: Session,
    bot: BotRow,
    strategy: Strategy,
    series: dict[str, list[DailyBar]],
    pf: Portfolio,
    now: datetime,
) -> list[DecisionRecord]:
    """AI 봇: 그날 기록된 AI 판단의 목표 비중으로 사고판다 (없으면 _NeedJudgment)."""
    target = max(b[-1].session_date for b in series.values())
    row = judgment_for(session, bot.id, target)
    if row is None:
        recent = recent_ok(session, bot.id, target, FEEDBACK_CALLS)
        prev = recent[-1] if recent else None
        plan = strategy.deposit_plan
        raise _NeedJudgment(
            make_request(
                series,
                cash=pf.cash,
                qtys={s: pf.qty(s) for s in series},
                contributed=pf.contributed or bot.initial_cash,
                monthly_deposit=plan.amount,
                leverage={s: leverage_of(session, s) for s in series},
                previous=prev.weights if prev else None,
                previous_date=prev.session_date if prev else None,
                as_of=now,
                candles=is_candle(strategy),
                past=[(r.session_date, r.weights or {}) for r in recent],
            )
        )
    ok = row.status == JudgmentStatus.OK
    missing = _NO_JUDGMENT.get(
        JudgmentStatus(row.status), "AI가 오늘 판단하지 못해 지금 그대로 둬요"
    )
    return rebalance(
        row.weights if ok else None,
        series,
        pf,
        bot_costs(bot),
        bot_limits(bot),
        row.reasons,
        missing=missing,
    )


def _summary(bot: BotRow, pf: Portfolio, closes: dict[str, Decimal]) -> BalanceSummary:
    """알림·로그용 잔고 요약 (판단일 종가 기준 평가). 수익률은 넣은 돈 대비.

    close·qty는 대표 종목(첫 종목) 값, closes는 종목별 종가 (주간 정리의 그냥 보유 비교용).
    """
    equity = pf.equity(closes)
    contributed = pf.contributed or bot.initial_cash
    return {
        "equity": str(money(equity)),
        "contributed": str(contributed),
        "total_return": str(round(equity / contributed - 1, 6)),
        "qty": str(pf.qty(bot.symbol)),
        "close": str(closes[bot.symbol]),
        "closes": {s: str(c) for s, c in closes.items()},
    }


def _decision_data(bot: BotRow, d: DecisionRecord, summary: BalanceSummary) -> DecisionData:
    data = DecisionData(
        **summary,
        symbol=d.symbol,
        action=d.action,
        target_long=d.target_long,
        holding=d.holding,
        indicators=to_jsonable(d.indicators),
        strategy=bot.strategy,
        params=bot.params,
    )
    if is_ai(bot.strategy):
        return AiDecisionData(**data, reason=d.reason)
    return data


def _commit_ok(
    session: Session,
    bot: BotRow,
    outcome: EvaluationOutcome,
    calendar: TradingCalendar,
    now: datetime,
    summary: BalanceSummary,
) -> EvaluationOutcome:
    assert outcome.session_date is not None
    bot.next_evaluation_at = next_evaluation_time(calendar, outcome.session_date)
    bot.updated_at = now
    run = session.get_one(RunRow, outcome.run_id)
    run.status, run.detail, run.session_date, run.finished_at = (
        outcome.status,
        outcome.detail,
        outcome.session_date,
        now,
    )
    for f in outcome.fills:
        add_event(
            session,
            now,
            "INFO",
            EventKind.SIM_FILL,
            f"{f.side} {f.qty.normalize():f}주 @ {f.price:.2f} "
            f"({f.fill_date} 시가, {f.signal_date} 판단)",
            bot_id=bot.id,
            run_id=outcome.run_id,
            data=FillData(
                symbol=f.symbol,
                side=f.side,
                signal_date=f.signal_date.isoformat(),
                fill_date=f.fill_date.isoformat(),
                qty=str(f.qty),
                price=str(f.price),
                commission=str(f.commission),
                realized_pnl=None if f.realized_pnl is None else str(f.realized_pnl),
            ),
        )
    # 같은 봉을 다시 평가한 경우(재시작·수동 실행)는 내부 기록만 남긴다 (알림·활동 표시 안 함).
    for d in outcome.decisions:
        add_event(
            session,
            now,
            "INFO",
            EventKind.DECISION,
            outcome.detail,
            bot_id=bot.id,
            run_id=outcome.run_id,
            data=_decision_data(bot, d, summary),
        )
    if not outcome.decisions:
        add_event(
            session,
            now,
            "INFO",
            EventKind.DECISION_REPEAT,
            outcome.detail,
            bot_id=bot.id,
            run_id=outcome.run_id,
            data=DecisionRepeatData(**summary, symbol=bot.symbol),
        )
    if outcome.decisions and is_week_end(calendar, outcome.session_date):
        add_event(
            session,
            now,
            "INFO",
            EventKind.WEEKLY_REPORT,
            f"{outcome.session_date} 주간 리포트",
            bot_id=bot.id,
            run_id=outcome.run_id,
            data=weekly_summary(session, bot, outcome.session_date, summary),
        )
    session.commit()
    return outcome
