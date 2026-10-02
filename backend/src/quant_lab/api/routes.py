"""조회와 명령 API. 토스를 호출하지 않고 DB만 읽는다 (project.md 3절 원칙 6)."""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_lab.api.schemas import (
    AccountView,
    ActivityItem,
    BacktestDetail,
    BacktestRequest,
    BacktestSummary,
    BarView,
    BotConfig,
    BotCreate,
    BotRename,
    BotView,
    CommandAccepted,
    CommandRequest,
    DecisionView,
    EquityPoint,
    EventView,
    InstrumentView,
    OrderView,
    PresetView,
    RunView,
    StrategyInfo,
)
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.messages import CATALOG, action_phrase, decision_reason, event_message
from quant_lab.config import get_settings
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES, Strategy
from quant_lab.persistence.backtests import to_jsonable
from quant_lab.persistence.bots import (
    add_event,
    create_bot,
    delete_bot,
    enqueue_command,
    get_bot,
    list_bots,
    reset_bot_history,
)
from quant_lab.persistence.db import get_session
from quant_lab.persistence.models import (
    BacktestRow,
    BotAccountRow,
    BotRow,
    DailyBarRow,
    DecisionRow,
    EventRow,
    InstrumentRow,
    LiveBarRow,
    QuoteRow,
    RunRow,
    SimOrderRow,
)

router = APIRouter(prefix="/api")
SessionDep = Annotated[Session, Depends(get_session)]


def _account(session: Session, bot: BotRow) -> AccountView:
    acc = session.get_one(BotAccountRow, bot.id)
    last = session.scalars(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == bot.symbol)
        .order_by(DailyBarRow.session_date.desc())
        .limit(1)
    ).first()
    if last is None:
        return AccountView(
            initial_cash=bot.initial_cash,
            cash=acc.cash,
            qty=acc.qty,
            avg_cost=acc.avg_cost,
            realized_pnl=acc.realized_pnl,
            last_close=None,
            last_close_date=None,
            market_value=None,
            unrealized_pnl=None,
            equity=None,
            total_return=None,
        )
    market_value = acc.qty * last.close
    equity = acc.cash + market_value
    live: dict[str, Any] = {}
    quote = session.get(QuoteRow, bot.symbol)
    if quote is not None:
        live_value = acc.qty * quote.price
        live = {
            "live_price": quote.price,
            "live_at": quote.quoted_at,
            "live_change": quote.price / last.close - 1 if last.close else None,
            "live_equity": acc.cash + live_value,
            "live_unrealized_pnl": live_value - acc.qty * acc.avg_cost,
        }
    return AccountView(
        initial_cash=bot.initial_cash,
        cash=acc.cash,
        qty=acc.qty,
        avg_cost=acc.avg_cost,
        realized_pnl=acc.realized_pnl,
        last_close=last.close,
        last_close_date=last.session_date,
        market_value=market_value,
        unrealized_pnl=market_value - acc.qty * acc.avg_cost,
        equity=equity,
        total_return=(equity / bot.initial_cash - 1) if bot.initial_cash else None,
        **live,
    )


def _decision(row: DecisionRow, bot: BotRow | None = None) -> DecisionView:
    view = DecisionView.model_validate(row, from_attributes=True)
    if bot is not None:
        strategy = row.strategy or {}
        view.plain_reason = decision_reason(
            strategy.get("name", bot.strategy),
            strategy.get("params", bot.params),
            row.indicators,
            row.target_long,
            row.holding,
        )
        view.plain_action = action_phrase(row.action, row.holding, row.symbol)
    return view


def _order(row: SimOrderRow) -> OrderView:
    return OrderView.model_validate(row, from_attributes=True)


def _bot_view(session: Session, bot: BotRow) -> BotView:
    last_decision = session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot.id)
        .order_by(DecisionRow.session_date.desc())
        .limit(1)
    ).first()
    pending = session.scalars(
        select(SimOrderRow).where(SimOrderRow.bot_id == bot.id, SimOrderRow.status == "PENDING")
    ).first()
    last_run = session.scalars(
        select(RunRow).where(RunRow.bot_id == bot.id).order_by(RunRow.started_at.desc()).limit(1)
    ).first()
    data_latest, data_fetched = session.execute(
        select(func.max(DailyBarRow.session_date), func.max(DailyBarRow.fetched_at)).where(
            DailyBarRow.symbol == bot.symbol
        )
    ).one()
    return BotView(
        id=bot.id,
        name=bot.name,
        symbol=bot.symbol,
        strategy=bot.strategy,
        params=bot.params,
        state=bot.state,
        state_reason=bot.state_reason,
        commission_rate=bot.commission_rate,
        slippage_bps=bot.slippage_bps,
        risk=bot.risk,
        next_evaluation_at=bot.next_evaluation_at,
        account=_account(session, bot),
        last_decision=_decision(last_decision, bot) if last_decision else None,
        pending_order=_order(pending) if pending else None,
        last_run=RunView.model_validate(last_run, from_attributes=True) if last_run else None,
        data_latest_date=data_latest,
        data_fetched_at=data_fetched,
        data_source=session.scalar(
            select(DailyBarRow.source)
            .where(DailyBarRow.symbol == bot.symbol)
            .order_by(DailyBarRow.session_date.desc())
            .limit(1)
        ),
    )


def _require_bot(session: Session, bot_id: int, *, for_update: bool = False) -> BotRow:
    # for_update: Worker 평가도 같은 행을 잠그므로, 평가 중이면 끝날 때까지 기다렸다가 바꾼다.
    bot = get_bot(session, bot_id, for_update=for_update)
    if bot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"봇 {bot_id}가 없습니다")
    return bot


@router.get("/bots")
def bots(session: SessionDep) -> list[BotView]:
    return [_bot_view(session, b) for b in list_bots(session) if not b.name.startswith("replay-")]


def _checked_strategy(config: BotConfig) -> Strategy:
    factory = STRATEGIES.get(config.strategy)
    if factory is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"알 수 없는 전략: {config.strategy}")
    try:
        return factory(**config.params)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"파라미터 오류: {exc}") from exc


def _limits(config: BotConfig) -> RiskLimits:
    return RiskLimits(
        max_position_value=config.max_position_value, max_order_value=config.max_order_value
    )


def _changes(before: dict[str, Any], after: dict[str, Any]) -> str:
    diff = [
        f"{k} {before.get(k)} → {v}"
        for k, v in after.items()
        if str(before.get(k)) != str(v)
        and not (before.get(k) is not None and v is not None and _same_number(before[k], v))
    ]
    return ", ".join(diff) or "변경 없음"


def _same_number(a: object, b: object) -> bool:
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except ArithmeticError:
        return False


@router.post("/bots", status_code=status.HTTP_201_CREATED)
def create(session: SessionDep, body: BotCreate) -> BotView:
    strategy = _checked_strategy(body)
    if session.scalar(select(BotRow.id).where(BotRow.name == body.name)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"같은 이름의 봇이 있습니다: {body.name}")
    now = datetime.now(UTC)
    bot = create_bot(
        session,
        name=body.name,
        symbol=body.symbol.upper(),
        strategy=strategy.name,
        params=strategy.params,
        initial_cash=body.initial_cash,
        costs=CostModel(commission_rate=body.commission_rate, slippage_bps=body.slippage_bps),
        limits=_limits(body),
        now=now,
    )
    add_event(
        session,
        now,
        "INFO",
        "config_change",
        f"봇 생성: {bot.symbol} {bot.strategy} {bot.params}",
        bot_id=bot.id,
        data={"after": body.model_dump(mode="json")},
    )
    session.commit()
    return _bot_view(session, bot)


@router.put("/bots/{bot_id}/config")
def update_config(session: SessionDep, bot_id: int, body: BotConfig) -> BotView:
    """실행 중에도 바꿀 수 있다. 다음 판단부터 적용된다 (평가와는 행 잠금으로 순서가 정해진다)."""
    bot = _require_bot(session, bot_id, for_update=True)
    strategy = _checked_strategy(body)
    before = {
        "strategy": bot.strategy,
        "params": bot.params,
        "commission_rate": str(bot.commission_rate),
        "slippage_bps": str(bot.slippage_bps),
        **bot.risk,
    }
    after = {
        "strategy": strategy.name,
        "params": strategy.params,
        "commission_rate": str(body.commission_rate),
        "slippage_bps": str(body.slippage_bps),
        **to_jsonable(_limits(body)),
    }
    now = datetime.now(UTC)
    bot.strategy, bot.params = strategy.name, strategy.params
    bot.commission_rate, bot.slippage_bps = body.commission_rate, body.slippage_bps
    bot.risk = to_jsonable(_limits(body))
    bot.updated_at = now
    add_event(
        session,
        now,
        "INFO",
        "config_change",
        f"설정 변경: {_changes(before, after)}",
        bot_id=bot.id,
        data={"before": before, "after": after},
    )
    session.commit()
    return _bot_view(session, bot)


@router.patch("/bots/{bot_id}")
def rename(session: SessionDep, bot_id: int, body: BotRename) -> BotView:
    bot = _require_bot(session, bot_id, for_update=True)
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "이름을 입력해 주세요")
    if name != bot.name:
        if session.scalar(select(BotRow.id).where(BotRow.name == name)) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"같은 이름의 봇이 있습니다: {name}")
        now = datetime.now(UTC)
        add_event(
            session,
            now,
            "INFO",
            "config_change",
            f"이름 변경: {bot.name} → {name}",
            bot_id=bot.id,
            data={"before": {"name": bot.name}, "after": {"name": name}},
        )
        bot.name, bot.updated_at = name, now
        session.commit()
    return _bot_view(session, bot)


@router.post("/bots/{bot_id}/reset")
def reset(session: SessionDep, bot_id: int) -> BotView:
    """처음부터 다시 시작: 판단·주문·실행 기록을 지우고 시작 금액으로. 설정·상태는 그대로."""
    bot = _require_bot(session, bot_id, for_update=True)
    now = datetime.now(UTC)
    reset_bot_history(session, bot, now)
    add_event(session, now, "INFO", "bot_reset", "처음부터 다시 시작", bot_id=bot.id)
    session.commit()
    return _bot_view(session, bot)


@router.delete("/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(session: SessionDep, bot_id: int) -> None:
    bot = _require_bot(session, bot_id, for_update=True)
    name, symbol = bot.name, bot.symbol
    delete_bot(session, bot_id)
    add_event(
        session,
        datetime.now(UTC),
        "INFO",
        "bot_deleted",
        f"봇 삭제: {name}",
        data={"name": name, "symbol": symbol},
    )
    session.commit()


@router.get("/bots/{bot_id}")
def bot(session: SessionDep, bot_id: int) -> BotView:
    return _bot_view(session, _require_bot(session, bot_id))


@router.post("/bots/{bot_id}/commands", status_code=status.HTTP_202_ACCEPTED)
def command(session: SessionDep, bot_id: int, body: CommandRequest) -> CommandAccepted:
    """명령은 DB에 기록만 한다. Worker가 다음 주기(15초 이내)에 처리한다."""
    _require_bot(session, bot_id)
    cmd = enqueue_command(session, bot_id, body.kind, datetime.now(UTC))
    session.commit()
    return CommandAccepted(id=cmd.id, bot_id=bot_id, kind=body.kind, created_at=cmd.created_at)


@router.get("/bots/{bot_id}/decisions")
def decisions(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[DecisionView]:
    rows = session.scalars(
        select(DecisionRow)
        .where(DecisionRow.bot_id == bot_id)
        .order_by(DecisionRow.session_date.desc())
        .limit(limit)
    )
    return [_decision(r) for r in rows]


@router.get("/bots/{bot_id}/orders")
def orders(
    session: SessionDep, bot_id: int, limit: Annotated[int, Query(le=500)] = 50
) -> list[OrderView]:
    rows = session.scalars(
        select(SimOrderRow)
        .where(SimOrderRow.bot_id == bot_id)
        .order_by(SimOrderRow.id.desc())
        .limit(limit)
    )
    return [_order(r) for r in rows]


@router.get("/bots/{bot_id}/equity")
def equity(session: SessionDep, bot_id: int) -> list[EquityPoint]:
    """홈 차트용 하루 단위 모의 자산. 첫 판단일부터 체결 기록을 장 마감 가격에 다시 적용한다."""
    bot = _require_bot(session, bot_id)
    first = session.scalar(
        select(func.min(DecisionRow.session_date)).where(DecisionRow.bot_id == bot_id)
    )
    start = first or bot.created_at.date()
    fills = [
        (o.fill_date, o.side, o.qty or 0, (o.qty or 0) * (o.price or 0), o.commission or 0)
        for o in session.scalars(
            select(SimOrderRow)
            .where(SimOrderRow.bot_id == bot_id, SimOrderRow.status == "FILLED")
            .order_by(SimOrderRow.fill_date, SimOrderRow.id)
        )
        if o.fill_date is not None
    ]
    bars = session.scalars(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == bot.symbol, DailyBarRow.session_date >= start)
        .order_by(DailyBarRow.session_date)
    )
    cash, qty, i = bot.initial_cash, 0, 0
    out: list[EquityPoint] = []
    for bar in bars:
        while i < len(fills) and fills[i][0] <= bar.session_date:
            _, side, n, notional, commission = fills[i]
            if side == "BUY":
                cash, qty = cash - notional - commission, qty + n
            else:
                cash, qty = cash + notional - commission, qty - n
            i += 1
        out.append(EquityPoint(date=bar.session_date, equity=cash + qty * bar.close))
    # 오늘 진행 중인 장이 있으면 실시간 가격으로 한 점을 더한다 (홈의 "지금 가치"와 같은 값).
    lb, quote = session.get(LiveBarRow, bot.symbol), session.get(QuoteRow, bot.symbol)
    if out and lb is not None and quote is not None and lb.session_date > out[-1].date:
        out.append(EquityPoint(date=lb.session_date, equity=cash + qty * quote.price, live=True))
    return out


@router.get("/events")
def events(
    session: SessionDep,
    bot_id: int | None = None,
    level: str | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(le=500)] = 100,
) -> list[EventView]:
    stmt = select(EventRow).order_by(EventRow.at.desc(), EventRow.id.desc()).limit(limit)
    if bot_id is not None:
        stmt = stmt.where(EventRow.bot_id == bot_id)
    if level:
        stmt = stmt.where(EventRow.level == level.upper())
    if kind:
        stmt = stmt.where(EventRow.kind == kind)
    return [EventView.model_validate(r, from_attributes=True) for r in session.scalars(stmt)]


@router.get("/bars/{symbol}")
def bars(
    session: SessionDep,
    symbol: str,
    start: date | None = None,
    limit: Annotated[int, Query(le=10_000)] = 600,
) -> list[BarView]:
    stmt = select(DailyBarRow).where(DailyBarRow.symbol == symbol.upper())
    if start:
        stmt = stmt.where(DailyBarRow.session_date >= start)
    rows = list(session.scalars(stmt.order_by(DailyBarRow.session_date.desc()).limit(limit)))
    out = [
        BarView(
            date=r.session_date, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume
        )
        for r in reversed(rows)
    ]
    # 완료 봉보다 새 날짜의 진행 중 봉이 있으면 끝에 붙인다 (차트 표시용).
    lb = session.get(LiveBarRow, symbol.upper())
    if lb is not None and (not out or lb.session_date > out[-1].date):
        out.append(
            BarView(
                date=lb.session_date,
                open=lb.open,
                high=lb.high,
                low=lb.low,
                close=lb.close,
                volume=lb.volume,
                live=True,
            )
        )
    return out


@router.get("/instruments")
def instruments(session: SessionDep) -> list[InstrumentView]:
    """관심 종목 + 봇 종목 (종목 버튼·레버리지 표시). 레버리지 배수는 Worker가 채운다."""
    watch = [s.strip().upper() for s in get_settings().watchlist_symbols.split(",") if s.strip()]
    watch += [s for s in session.scalars(select(BotRow.symbol).distinct()) if s not in watch]
    infos = {r.symbol: r for r in session.scalars(select(InstrumentRow))}
    quotes = {q.symbol: q for q in session.scalars(select(QuoteRow))}
    return [
        InstrumentView(
            symbol=s,
            name=infos[s].name if s in infos else None,
            leverage_factor=infos[s].leverage_factor if s in infos else None,
            live_price=quotes[s].price if s in quotes else None,
            live_at=quotes[s].quoted_at if s in quotes else None,
        )
        for s in watch
    ]


@router.get("/strategies")
def strategies() -> list[StrategyInfo]:
    out = []
    for name, factory in STRATEGIES.items():
        info = CATALOG[name]
        out.append(
            StrategyInfo(
                name=name,
                nickname=info.nickname,
                emoji=info.emoji,
                summary=info.summary,
                risk=info.risk,
                trades=info.trades,
                presets=[
                    PresetView(key=p.key, label=p.label, params=p.params) for p in info.presets
                ],
                default_params=factory().params,
            )
        )
    return out


@router.get("/activity")
def activity(
    session: SessionDep,
    bot_id: int | None = None,
    kind: str | None = None,
    limit: Annotated[int, Query(le=100)] = 20,
) -> list[ActivityItem]:
    """최근 활동을 쉬운 말로. 내부 기록(재시작, 중복 평가 등)은 빼고 보여준다."""
    bots = {b.id: b for b in list_bots(session)}
    stmt = select(EventRow).order_by(EventRow.id.desc()).limit(limit * 5)
    if bot_id is not None:
        stmt = stmt.where(EventRow.bot_id == bot_id)
    if kind:
        stmt = stmt.where(EventRow.kind == kind)
    items: list[ActivityItem] = []
    for e in session.scalars(stmt):
        bot = bots.get(e.bot_id) if e.bot_id else None
        msg = event_message(
            e.kind,
            e.level,
            e.message,
            e.data,
            bot.name if bot else None,
            bot.symbol if bot else None,
        )
        if msg is not None:
            items.append(
                ActivityItem(
                    id=e.id, at=e.at, icon=msg.icon, title=msg.title, body=msg.body, level=msg.level
                )
            )
        if len(items) >= limit:
            break
    return items


@router.post("/backtests", status_code=status.HTTP_201_CREATED)
def run_backtest(session: SessionDep, body: BacktestRequest) -> BacktestDetail:
    """일봉 1종목 백테스트는 수 초면 끝나서 요청 안에서 실행한다 (스레드풀, 토스 호출 없음)."""
    factory = STRATEGIES.get(body.strategy)
    if factory is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"알 수 없는 전략: {body.strategy}")
    try:
        strategy = factory(**body.params)
        run = backtest_symbol(
            session,
            body.symbol.upper(),
            strategy,
            initial_cash=body.initial_cash,
            costs=CostModel(commission_rate=body.commission_rate, slippage_bps=body.slippage_bps),
            limits=RiskLimits(),
            start=body.start,
            end=body.end,
            now=datetime.now(UTC),
            save=True,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    assert run.saved_id is not None
    return backtest(session, run.saved_id)


@router.get("/backtests")
def backtests(
    session: SessionDep, symbol: str | None = None, limit: Annotated[int, Query(le=100)] = 20
) -> list[BacktestSummary]:
    stmt = select(BacktestRow).order_by(BacktestRow.created_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(BacktestRow.symbol == symbol.upper())
    return [BacktestSummary.model_validate(r, from_attributes=True) for r in session.scalars(stmt)]


@router.get("/backtests/{backtest_id}")
def backtest(session: SessionDep, backtest_id: uuid.UUID) -> BacktestDetail:
    row = session.get(BacktestRow, backtest_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "백테스트가 없습니다")
    return BacktestDetail.model_validate(row, from_attributes=True)
