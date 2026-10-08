"""계산해 보기: 시험해 보기(백테스트), 평행세계의 나, 따라 하기. 입력 검증까지 여기서 한다."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.bots import check_cash, check_strategy, check_weights, require_bot
from quant_lab.application.errors import Invalid
from quant_lab.application.parallel import World, parallel_worlds
from quant_lab.application.plan import Plan, follow_plan
from quant_lab.domain.bars import TradingCalendar
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import DipSaver, deposit_plan
from quant_lab.persistence.bots import active_weights, bot_costs
from quant_lab.persistence.models import BacktestRow, BotRow, DecisionRow

COPY_STRATEGY = "dip_saver"  # 따라 하기·평행세계는 나 카피 봇(나처럼 투자) 전용


def run_backtest(
    session: Session,
    *,
    symbol: str,
    symbols: Sequence[tuple[str, int]] | None,
    strategy: str,
    params: dict[str, int],
    start: date | None,
    end: date | None,
    initial_cash: Decimal | None,
    costs: CostModel,
    now: datetime,
    keep_latest: int | None = None,
) -> uuid.UUID:
    """일봉 백테스트를 계산해 저장하고 id를 돌려준다. keep_latest면 최근 것만 남긴다 (공개 데모)."""
    chosen = check_strategy(strategy, params)
    check_cash(initial_cash)
    weights = check_weights(symbol, symbols, chosen)
    plan = deposit_plan(chosen)
    # 모으기 전략은 첫 달 입금액으로 시작한다 ("월급부터 모았다면").
    initial = initial_cash or (plan.amount if plan else Decimal(10_000))
    try:
        run = backtest_symbol(
            session,
            next(iter(weights)),
            chosen,
            weights=weights,
            initial_cash=initial,
            costs=costs,
            limits=RiskLimits(),
            start=start,
            end=end,
            now=now,
            save=True,
        )
    except (TypeError, ValueError) as exc:
        raise Invalid(str(exc)) from exc
    assert run.saved_id is not None
    if keep_latest is not None:
        keep = select(BacktestRow.id).order_by(BacktestRow.created_at.desc()).limit(keep_latest)
        session.execute(delete(BacktestRow).where(BacktestRow.id.not_in(keep)))
        session.commit()
    return run.saved_id


def parallel_request(
    session: Session,
    *,
    symbol: str,
    symbols: Sequence[tuple[str, int]] | None,
    params: dict[str, int],
    start: date | None,
    end: date | None,
    initial_cash: Decimal | None,
) -> list[World]:
    """평행세계의 나: 내 규칙을 하나씩 바꾼 나들을 같은 기간에 계산한다 (저장하지 않음)."""
    try:
        strategy = DipSaver(**params)
    except (TypeError, ValueError) as exc:
        raise Invalid(str(exc)) from exc
    weights = check_weights(symbol, symbols, strategy)
    try:
        return parallel_worlds(
            session,
            weights,
            strategy.params,
            start=start,
            end=end,
            initial_cash=initial_cash or Decimal(strategy.deposit),
            costs=CostModel(commission_rate=Decimal("0.001"), slippage_bps=Decimal(5)),
        )
    except (TypeError, ValueError) as exc:
        raise Invalid(str(exc)) from exc


@dataclass(frozen=True)
class BotParallel:
    start: date | None
    worlds: list[World] = field(default_factory=list)
    note: str | None = None  # 아직 계산할 수 없을 때 화면에 보여줄 말


def _copy_bot(session: Session, bot_id: int) -> BotRow:
    bot = require_bot(session, bot_id)
    if bot.strategy != COPY_STRATEGY:
        raise Invalid("나 카피 봇만 볼 수 있어요")
    return bot


def bot_parallel(session: Session, bot_id: int) -> BotParallel:
    """운영 중인 나처럼 투자 봇의 평행세계: 첫 판단일부터 지금 규칙으로 다시 계산한다."""
    bot = _copy_bot(session, bot_id)
    first = session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot_id)
    )
    if first is None:
        return BotParallel(None, note="아직 첫 판단 전이에요.")
    try:
        worlds = parallel_worlds(
            session,
            active_weights(bot),
            bot.params,
            start=first,
            end=None,
            initial_cash=bot.initial_cash,
            costs=bot_costs(bot),
        )
    except ValueError:
        return BotParallel(first, note="시작한 지 얼마 안 돼서 아직 비교할 날이 없어요.")
    return BotParallel(first, worlds)


def bot_plan(session: Session, bot_id: int, calendar: TradingCalendar) -> Plan | None:
    """따라 하기: 다음 입금일에 할 일, 조건까지 거리, 모아 둔 돈의 내력. 봉이 부족하면 None."""
    return follow_plan(session, _copy_bot(session, bot_id), calendar)
