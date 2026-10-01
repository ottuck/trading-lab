"""README 화면 캡처용 데모 DB를 만든다. 토스 데이터 대신 합성 시세만 쓴다.

    cd backend
    DATABASE_URL=postgresql+psycopg://quant:quant@localhost:5432/quant_lab_demo \
        uv run python ../scripts/demo_seed.py

DB를 새로 만들고(기존 데모 DB는 지움) 마이그레이션 → 합성 일봉 → 백테스트 → 봇 replay 순서로 채운다.
"""

import io
import math
import random
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.orm import sessionmaker

from quant_lab.adapters.market_calendar import get_calendar
from quant_lab.application.backtesting import backtest_symbol
from quant_lab.application.replay import replay_bot
from quant_lab.config import get_settings
from quant_lab.domain.bars import DailyBar
from quant_lab.domain.bot import BotState
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.domain.strategy import STRATEGIES
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot
from quant_lab.persistence.db import make_engine

SYMBOL = "DEMO"
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"


def synthetic_bars(sessions: list[date], seed: int = 7) -> list[DailyBar]:
    """국면이 바뀌는 기하 브라운 운동. 강세·약세·횡보가 섞여 추세 신호가 나온다."""
    rng = random.Random(seed)
    price = 100.0
    bars = []
    for i, day in enumerate(sessions):
        regime = math.sin(i / 160) * 0.0012 + (-0.002 if 900 < i < 1050 else 0.0004)
        ret = regime + rng.gauss(0, 0.012)
        open_ = price * (1 + rng.gauss(0, 0.003))
        close = price * math.exp(ret)
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.004)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.004)))

        def d(x: float) -> Decimal:
            return Decimal(f"{x:.2f}")

        bars.append(
            DailyBar(
                SYMBOL,
                day,
                d(open_),
                d(high),
                d(low),
                d(close),
                Decimal(rng.randint(5, 20) * 100_000),
            )
        )
        price = close
    return bars


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    url = get_settings().database_url
    name = make_url(url).database
    if not name or "demo" not in name:
        raise SystemExit("DATABASE_URL이 데모 DB(이름에 demo 포함)를 가리켜야 합니다.")

    admin = make_engine(
        make_url(url).set(database="postgres").render_as_string(hide_password=False)
    )
    with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    cfg = Config(BACKEND_DIR / "alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    calendar = get_calendar()
    sessions = calendar.sessions(date(2020, 1, 2), date(2026, 9, 30))
    bars = synthetic_bars(sessions)
    make_session = sessionmaker(make_engine(url))
    now = datetime.now(UTC)
    with make_session() as session:
        upsert_daily_bars(session, bars, "synthetic", now)
        session.commit()
        for strategy, params in [
            ("donchian", {"entry": 55, "exit": 20}),
            ("trend_filter", {"sma": 200}),
            ("sma_cross", {"fast": 50, "slow": 200}),
        ]:
            backtest_symbol(
                session,
                SYMBOL,
                STRATEGIES[strategy](**params),
                initial_cash=Decimal(10_000),
                costs=CostModel(),
                limits=RiskLimits(),
                start=date(2021, 1, 4),
                end=None,
                now=now,
                save=True,
            )
        bot = create_bot(
            session,
            name="demo-sma",
            symbol=SYMBOL,
            strategy="sma_cross",
            params={"fast": 50, "slow": 200},
            initial_cash=Decimal(10_000),
            costs=CostModel(),
            limits=RiskLimits(),
            now=now,
        )
        session.commit()
        bot_id = bot.id

    replay_bot(make_session, bot_id, calendar, date(2025, 1, 2), date(2026, 9, 30))
    with make_session() as session:
        bot = session.get_one(type(bot), bot_id)
        bot.state = BotState.RUNNING
        session.commit()
    print(f"데모 DB 준비 완료: {name} (합성 일봉 {len(bars)}개, 봇 {bot_id})")


if __name__ == "__main__":
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
