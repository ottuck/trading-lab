from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from quant_lab.application.backtesting import backtest_symbol
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import SmaCross
from quant_lab.persistence.backtests import list_backtests
from quant_lab.persistence.bars import upsert_daily_bars
from tests.fakes import make_bars

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def test_start_date_includes_warmup_and_result_is_saved(session: Session) -> None:
    bars = make_bars("QQQ", [100 + (i % 11) for i in range(100)])
    upsert_daily_bars(session, bars, "test", NOW)
    session.commit()
    strategy = SmaCross(fast=3, slow=10)

    run = backtest_symbol(
        session,
        "QQQ",
        strategy,
        initial_cash=Decimal(10_000),
        costs=CostModel(),
        limits=RiskLimits(),
        start=bars[50].session_date,
        end=None,
        now=NOW,
        save=True,
    )

    assert run.result.equity[0].session_date == bars[50].session_date
    saved = list_backtests(session, "QQQ")
    assert [r.id for r in saved] == [run.saved_id]
    row = saved[0]
    assert row.params == {"fast": 3, "slow": 10}
    assert row.data_start == bars[41].session_date
    assert Decimal(row.metrics["final_equity"]) == run.result.metrics.final_equity
    assert row.commission_rate == Decimal("0.001")
