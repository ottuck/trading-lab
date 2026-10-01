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

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_lab.adapters.toss.client import TossAuthError, TossError, TossForbiddenError
from quant_lab.application.bar_sync import DEFAULT_SETTLE
from quant_lab.application.market import MarketData
from quant_lab.domain.bars import TradingCalendar, check_daily_bars, is_completed
from quant_lab.domain.bot import BotState
from quant_lab.domain.portfolio import Portfolio, money
from quant_lab.domain.strategy import STRATEGIES, Strategy
from quant_lab.domain.trading import Action, DecisionRecord, Fill, decide, execute
from quant_lab.persistence.backtests import to_jsonable
from quant_lab.persistence.bars import load_daily_bars
from quant_lab.persistence.bots import (
    add_event,
    bot_costs,
    bot_limits,
    get_bot,
    load_account,
    pending_order,
    save_account,
    set_bot_state,
)
from quant_lab.persistence.models import BotRow, DecisionRow, RunRow, SimOrderRow

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
    decision: DecisionRecord | None = None
    fill: Fill | None = None


class _Skip(Exception):
    """신규 주문 없이 이번 평가를 건너뛴다. 잠시 뒤 다시 시도한다."""


def build_strategy(bot: BotRow) -> Strategy:
    return STRATEGIES[bot.strategy](**bot.params)


def latest_completed_session(
    calendar: TradingCalendar, now: datetime, settle: timedelta = DEFAULT_SETTLE
) -> date:
    today = now.date()
    sessions = calendar.sessions(today - timedelta(days=14), today)
    done = [s for s in sessions if is_completed(s, calendar, now, settle)]
    if not done:
        raise _Skip("최근 2주 안에 완료된 거래일이 없습니다")
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
) -> EvaluationOutcome:
    run = RunRow(id=uuid.uuid4(), bot_id=bot_id, trigger=trigger, started_at=now, status="RUNNING")
    session.add(run)
    session.commit()
    run_id = run.id

    try:
        outcome = _evaluate(session, bot_id, run_id, market, calendar, now)
    except _Skip as skip:
        session.rollback()
        outcome = EvaluationOutcome(run_id, RunStatus.SKIPPED, None, str(skip))
        _finish(session, bot_id, outcome, now, level="WARN", retry=True)
    except (TossForbiddenError, TossAuthError) as exc:
        # 허용 IP·토큰 경합은 기다려도 풀리지 않는다. 사람이 확인할 때까지 멈춘다.
        session.rollback()
        outcome = EvaluationOutcome(run_id, RunStatus.ERROR, None, f"토스 인증·권한 오류: {exc}")
        _finish(session, bot_id, outcome, now, level="ERROR", to_error=True)
    except (TossError, httpx.HTTPError) as exc:
        session.rollback()
        outcome = EvaluationOutcome(run_id, RunStatus.SKIPPED, None, f"토스 호출 실패: {exc}")
        _finish(session, bot_id, outcome, now, level="WARN", retry=True)
    except Exception as exc:
        session.rollback()
        log.exception("평가 실패 bot=%s", bot_id)
        outcome = EvaluationOutcome(run_id, RunStatus.ERROR, None, f"예상하지 못한 오류: {exc!r}")
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
    add_event(
        session,
        now,
        level,
        f"run_{outcome.status.lower()}",
        outcome.detail,
        bot_id=bot_id,
        run_id=outcome.run_id,
    )
    session.commit()


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
        raise _Skip(f"봇 {bot_id}가 없습니다")
    strategy = build_strategy(bot)
    costs, limits = bot_costs(bot), bot_limits(bot)

    # 1) 장 운영 판정
    target = latest_completed_session(calendar, now)
    confirmed = market.confirm_session(target)
    if confirmed is False:
        raise _Skip(f"{target}: XNYS는 거래일이지만 토스 캘린더는 아닙니다")

    # 2) 완료 봉 수집·검증
    sync = market.refresh(session, bot.symbol, now)
    if sync is not None and sync.issues:
        raise _Skip(f"새 일봉 품질 문제 {len(sync.issues)}건: {sync.issues[0].kind}")
    bars = load_daily_bars(session, bot.symbol, end=target)
    if not bars or bars[-1].session_date != target:
        last = bars[-1].session_date if bars else None
        raise _Skip(f"{target} 일봉이 아직 없습니다 (마지막 {last})")
    window = bars[-(strategy.warmup + 2) :]
    issues = check_daily_bars(window, calendar)
    if issues:
        raise _Skip(f"판단 구간 일봉 문제: {issues[0].kind} {issues[0].session_date}")

    # 3) 이전 대기 주문을 T+1 시가로 체결
    pf = load_account(session, bot.id)
    fill: Fill | None = None
    order = pending_order(session, bot.id)
    if order is not None and order.signal_date < target:
        fill_bar = next(b for b in bars if b.session_date > order.signal_date)
        intent = DecisionRecord(order.signal_date, Action(order.side), True, False, "", {})
        fill = execute(pf, intent, fill_bar, costs, limits)
        order.fill_date = fill_bar.session_date
        if fill is None:
            order.status = "UNFILLED"
            order.note = "체결 시점 현금·위험 한도로 살 수 있는 수량이 없음"
        else:
            order.status = "FILLED"
            order.qty, order.price, order.commission = fill.qty, fill.price, fill.commission
            order.realized_pnl = fill.realized_pnl
        session.flush()

    # 4) 이미 판단한 봉이면 아무것도 하지 않는다 (수동 실행 반복 등)
    existing = session.scalars(
        select(DecisionRow).where(
            DecisionRow.bot_id == bot.id,
            DecisionRow.symbol == bot.symbol,
            DecisionRow.session_date == target,
            DecisionRow.mode == MODE,
        )
    ).first()
    if existing is not None:
        save_account(session, bot.id, pf, now)
        outcome = EvaluationOutcome(
            run_id, RunStatus.OK, target, f"{target} 판단은 이미 있음", fill=fill
        )
        return _commit_ok(session, bot, outcome, calendar, now, _summary(bot, pf, bars[-1].close))

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
                "missed_sessions",
                f"판단 누락 {len(missed)}일: {missed[0]} ~ {missed[-1]}",
                bot_id=bot.id,
                run_id=run_id,
            )

    # 5) 전략 판단·위험 검사·모의 주문
    decision = decide(strategy, bars, pf, costs, limits)
    if decision is None:
        raise _Skip(f"봉이 부족합니다 ({len(bars)}개, 필요 {strategy.warmup}개)")
    row = DecisionRow(
        bot_id=bot.id,
        symbol=bot.symbol,
        session_date=target,
        mode=MODE,
        run_id=run_id,
        strategy={
            "name": bot.strategy,
            "params": bot.params,
            "risk": bot.risk,
            "commission_rate": str(costs.commission_rate),
            "slippage_bps": str(costs.slippage_bps),
        },
        action=decision.action,
        target_long=decision.target_long,
        holding=decision.holding,
        reason=decision.reason,
        indicators=to_jsonable(decision.indicators),
        blocked=decision.blocked,
        created_at=now,
    )
    session.add(row)
    try:
        session.flush()
        if decision.action is not Action.HOLD:
            session.add(
                SimOrderRow(
                    bot_id=bot.id,
                    decision_id=row.id,
                    side=decision.action,
                    status="PENDING",
                    signal_date=target,
                    created_at=now,
                )
            )
            session.flush()
    except IntegrityError as exc:
        # 다른 Worker가 같은 봉을 먼저 판단했다. 이 실행의 변경은 모두 버린다.
        raise _Skip(f"{target} 판단 중복 차단 (DB 유일 제약)") from exc

    save_account(session, bot.id, pf, now)
    detail = f"{target} {decision.action}: {decision.reason}"
    if decision.blocked:
        detail += f" (차단: {decision.blocked})"
    outcome = EvaluationOutcome(run_id, RunStatus.OK, target, detail, decision=decision, fill=fill)
    return _commit_ok(session, bot, outcome, calendar, now, _summary(bot, pf, bars[-1].close))


def _summary(bot: BotRow, pf: Portfolio, close: Decimal) -> dict[str, str | int]:
    """알림·로그용 잔고 요약 (판단일 종가 기준 평가)."""
    equity = pf.equity(close)
    return {
        "equity": str(money(equity)),
        "total_return": str(round(equity / bot.initial_cash - 1, 6)),
        "qty": pf.qty,
        "close": str(close),
    }


def _commit_ok(
    session: Session,
    bot: BotRow,
    outcome: EvaluationOutcome,
    calendar: TradingCalendar,
    now: datetime,
    summary: dict[str, str | int],
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
    if outcome.fill is not None:
        f = outcome.fill
        add_event(
            session,
            now,
            "INFO",
            "sim_fill",
            f"{f.side} {f.qty}주 @ {f.price:.2f} ({f.fill_date} 시가, {f.signal_date} 판단)",
            bot_id=bot.id,
            run_id=outcome.run_id,
            data=to_jsonable(f),
        )
    action = outcome.decision.action if outcome.decision else None
    add_event(
        session,
        now,
        "INFO",
        "decision",
        outcome.detail,
        bot_id=bot.id,
        run_id=outcome.run_id,
        data={"action": action, **summary} if action else summary,
    )
    session.commit()
    return outcome
