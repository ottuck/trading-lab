import dataclasses
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from trading_lab import __version__
from trading_lab.domain.backtest import BacktestResult
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.domain.trading import Action
from trading_lab.persistence.models import BacktestRow


def to_jsonable(value: Any) -> Any:
    """Decimal은 문자열로 저장해 정밀도를 잃지 않는다."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def save_backtest(
    session: Session,
    *,
    symbol: str,
    strategy: str,
    params: dict[str, int],
    costs: CostModel,
    limits: RiskLimits,
    result: BacktestResult,
    data_start: date,
    created_at: datetime,
    weights: dict[str, int] | None = None,
) -> uuid.UUID:
    actions = [d for d in result.decisions if d.action is not Action.HOLD or d.blocked]
    row = BacktestRow(
        id=uuid.uuid4(),
        created_at=created_at,
        code_version=__version__,
        symbol=symbol,
        symbols=[{"symbol": s, "weight": w} for s, w in weights.items()]
        if weights and len(weights) > 1
        else None,
        strategy=strategy,
        params=params,
        data_start=data_start,
        data_end=result.metrics.end,
        initial_cash=result.metrics.initial_cash,
        commission_rate=costs.commission_rate,
        slippage_bps=costs.slippage_bps,
        risk=to_jsonable(limits),
        metrics=to_jsonable(result.metrics),
        fills=to_jsonable(result.fills),
        actions=to_jsonable(actions),
        equity=to_jsonable(result.equity),
    )
    _drop_same_condition(session, row)
    session.add(row)
    session.commit()
    return row.id


def _drop_same_condition(session: Session, new: BacktestRow) -> None:
    """같은 조건으로 다시 시험하면 지난 결과를 지우고 새 결과만 남긴다 (같은 것이 쌓이지 않게).

    같은 조건: 종목·비율·전략·규칙·금액·비용이 같고 시험 시작이 같은 달.
    시작일은 날마다 하루씩 밀리므로 달 단위로 본다.
    """
    month = str(new.metrics["start"])[:7]
    same = select(BacktestRow).where(
        BacktestRow.symbol == new.symbol,
        BacktestRow.strategy == new.strategy,
        BacktestRow.initial_cash == new.initial_cash,
        BacktestRow.commission_rate == new.commission_rate,
        BacktestRow.slippage_bps == new.slippage_bps,
    )
    for old in session.scalars(same):
        if (
            old.params == new.params
            and old.symbols == new.symbols
            and old.risk == new.risk
            and str(old.metrics["start"])[:7] == month
        ):
            session.delete(old)


def list_backtests(
    session: Session, symbol: str | None = None, limit: int = 20
) -> list[BacktestRow]:
    stmt = select(BacktestRow).order_by(BacktestRow.created_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(BacktestRow.symbol == symbol)
    return list(session.scalars(stmt))


def keep_latest_backtests(session: Session, keep: int) -> None:
    """최신 keep개만 두고 지운다 (시험해 보기가 계속 쌓이지 않게)."""
    newest = select(BacktestRow.id).order_by(BacktestRow.created_at.desc()).limit(keep)
    session.execute(delete(BacktestRow).where(BacktestRow.id.not_in(newest)))
    session.commit()
