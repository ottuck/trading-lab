"""Worker 루프: heartbeat → 명령 처리 → 예정된 평가."""

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, func, select
from sqlalchemy.orm import Session

from quant_lab.application.dry_run import (
    EvaluationOutcome,
    Trigger,
    evaluate_bot,
    latest_completed_session,
)
from quant_lab.application.market import MarketData
from quant_lab.domain.bars import TradingCalendar
from quant_lab.domain.bot import (
    BotState,
    CommandKind,
    InvalidTransitionError,
    apply_command,
    state_after_restart,
)
from quant_lab.persistence.bars import latest_session_date
from quant_lab.persistence.bots import add_event, get_bot, set_bot_state
from quant_lab.persistence.models import BotRow, CommandRow

# 같은 DB에 Worker가 둘 뜨지 않게 하는 PostgreSQL advisory lock 키 ("QLAB")
WORKER_LOCK_KEY = 0x514C4142
WATCHLIST_CHECK_INTERVAL = timedelta(minutes=30)

log = logging.getLogger(__name__)


def try_acquire_worker_lock(conn: Connection) -> bool:
    """세션 수준 잠금. conn이 열려 있는 동안 유지된다."""
    acquired = bool(conn.execute(select(func.pg_try_advisory_lock(WORKER_LOCK_KEY))).scalar())
    # 트랜잭션을 열어 둔 채 두지 않는다 (idle in transaction 타임아웃에 연결이 끊기지 않게).
    conn.commit()
    return acquired


def release_worker_lock(conn: Connection) -> None:
    """연결 풀에 돌려줘도 세션 잠금은 남으므로 명시적으로 푼다."""
    conn.execute(select(func.pg_advisory_unlock(WORKER_LOCK_KEY)))
    conn.commit()


class Worker:
    def __init__(
        self,
        make_session: Callable[[], Session],
        market: MarketData,
        calendar: TradingCalendar,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        watchlist: Sequence[str] = (),
    ) -> None:
        self.make_session = make_session
        self.market = market
        self.calendar = calendar
        self.now = now
        self.watchlist = list(watchlist)
        self._watchlist_checked_at: datetime | None = None
        self._watchlist_failing: set[str] = set()

    def recover_after_restart(self) -> None:
        now = self.now()
        with self.make_session() as session:
            for bot in session.scalars(select(BotRow).with_for_update()):
                new = state_after_restart(BotState(bot.state))
                if new != bot.state:
                    set_bot_state(session, bot, new, "Worker 재시작 후 확인 대기", now)
                    add_event(
                        session,
                        now,
                        "WARN",
                        "restart_pause",
                        "Worker 재시작으로 일시정지했습니다. 확인 후 재개하세요.",
                        bot_id=bot.id,
                    )
            session.commit()

    def tick(self) -> list[EvaluationOutcome]:
        outcomes = self.process_commands()
        outcomes += self.run_due_bots()
        self.sync_watchlist()
        return outcomes

    def sync_watchlist(self) -> list[str]:
        """관심 종목 일봉을 최신 완료 거래일까지 맞춘다 (백테스트용). 30분에 한 번만 확인한다.

        봇 평가와 독립적이며, 실패해도 경고만 남기고 판단·모의 체결에는 영향이 없다.
        """
        now = self.now()
        if not self.watchlist or (
            self._watchlist_checked_at is not None
            and now - self._watchlist_checked_at < WATCHLIST_CHECK_INTERVAL
        ):
            return []
        self._watchlist_checked_at = now
        try:
            target = latest_completed_session(self.calendar, now)
        except Exception:
            return []
        synced: list[str] = []
        with self.make_session() as session:
            for symbol in self.watchlist:
                latest = latest_session_date(session, symbol)
                if latest is not None and latest >= target:
                    continue
                try:
                    result = self.market.refresh(session, symbol, now)
                except Exception as exc:
                    session.rollback()
                    # 같은 종목이 계속 실패하면 경고(알림)는 처음 한 번만 남긴다.
                    level = "INFO" if symbol in self._watchlist_failing else "WARN"
                    self._watchlist_failing.add(symbol)
                    add_event(
                        session, now, level, "watchlist_sync", f"{symbol} 일봉 갱신 실패: {exc}"
                    )
                    session.commit()
                    continue
                self._watchlist_failing.discard(symbol)
                if result is not None:
                    synced.append(f"{symbol}+{result.saved}")
        if synced:
            with self.make_session() as session:
                add_event(
                    session,
                    now,
                    "INFO",
                    "watchlist_sync",
                    f"관심 종목 일봉 갱신 ({target}): {', '.join(synced)}",
                )
                session.commit()
        return synced

    def process_commands(self) -> list[EvaluationOutcome]:
        outcomes: list[EvaluationOutcome] = []
        with self.make_session() as session:
            ids = list(
                session.scalars(
                    select(CommandRow.id)
                    .where(CommandRow.processed_at.is_(None))
                    .order_by(CommandRow.created_at, CommandRow.id)
                )
            )
        for command_id in ids:
            with self.make_session() as session:
                outcome = self._process_command(session, command_id)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes

    def _process_command(self, session: Session, command_id: int) -> EvaluationOutcome | None:
        now = self.now()
        cmd = session.get_one(CommandRow, command_id, with_for_update=True)
        if cmd.processed_at is not None:
            return None
        kind = CommandKind(cmd.kind)
        # 처리 표시를 먼저 저장해서, 처리 중 Worker가 죽어도 같은 명령을 두 번 실행하지 않게 한다.
        cmd.processed_at = now
        bot = get_bot(session, cmd.bot_id, for_update=True)
        if bot is None:
            cmd.result, cmd.detail = "REJECTED", "봇이 없습니다"
            session.commit()
            return None

        if kind is CommandKind.RUN_ONCE:
            cmd.result = "OK"
            session.commit()
            outcome = evaluate_bot(
                session,
                cmd.bot_id,
                market=self.market,
                calendar=self.calendar,
                now=now,
                trigger=Trigger.MANUAL,
            )
            cmd.detail = outcome.detail
            session.commit()
            return outcome

        try:
            new = apply_command(BotState(bot.state), kind)
        except InvalidTransitionError as exc:
            cmd.result, cmd.detail = "REJECTED", str(exc)
        else:
            set_bot_state(session, bot, new, None, now)
            if kind is CommandKind.START:
                bot.next_evaluation_at = (
                    now  # 바로 한 번 평가한다 (이미 판단한 봉이면 아무것도 안 함)
                )
            cmd.result, cmd.detail = "OK", f"{kind} → {new}"
            add_event(session, now, "INFO", "command", f"{kind}: {new}", bot_id=bot.id)
        session.commit()
        return None

    def run_due_bots(self) -> list[EvaluationOutcome]:
        now = self.now()
        with self.make_session() as session:
            due = list(
                session.scalars(
                    select(BotRow.id).where(
                        BotRow.state == BotState.RUNNING,
                        (BotRow.next_evaluation_at.is_(None)) | (BotRow.next_evaluation_at <= now),
                    )
                )
            )
        outcomes = []
        for bot_id in due:
            with self.make_session() as session:
                outcome = evaluate_bot(
                    session,
                    bot_id,
                    market=self.market,
                    calendar=self.calendar,
                    now=now,
                    trigger=Trigger.SCHEDULED,
                )
                log.info("평가 bot=%s %s %s", bot_id, outcome.status, outcome.detail)
                outcomes.append(outcome)
        return outcomes
