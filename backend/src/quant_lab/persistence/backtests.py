import dataclasses
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab import __version__
from quant_lab.domain.backtest import BacktestResult
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.trading import Action
from quant_lab.persistence.models import BacktestRow


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
) -> uuid.UUID:
    actions = [d for d in result.decisions if d.action is not Action.HOLD or d.blocked]
    row = BacktestRow(
        id=uuid.uuid4(),
        created_at=created_at,
        code_version=__version__,
        symbol=symbol,
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
    session.add(row)
    session.commit()
    return row.id


def list_backtests(
    session: Session, symbol: str | None = None, limit: int = 20
) -> list[BacktestRow]:
    stmt = select(BacktestRow).order_by(BacktestRow.created_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(BacktestRow.symbol == symbol)
    return list(session.scalars(stmt))
