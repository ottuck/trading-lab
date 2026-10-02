from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.api.main import app
from quant_lab.application.dry_run import Trigger, evaluate_bot
from quant_lab.application.market import StoredMarket
from quant_lab.domain.bot import BotState
from quant_lab.domain.portfolio import CostModel, RiskLimits
from quant_lab.persistence.bars import upsert_daily_bars
from quant_lab.persistence.bots import create_bot
from quant_lab.persistence.db import get_session
from quant_lab.persistence.heartbeat import record_heartbeat
from quant_lab.persistence.models import BotRow, CommandRow
from tests.fakes import WeekdayCalendar, make_bars

CAL = WeekdayCalendar()
BARS = make_bars("QQQ", [100 + i for i in range(30)])


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def bot_id(session: Session) -> int:
    upsert_daily_bars(session, BARS, "test", datetime(2026, 1, 1, tzinfo=UTC))
    bot = create_bot(
        session,
        name="qqq",
        symbol="QQQ",
        strategy="sma_cross",
        params={"fast": 3, "slow": 5},
        initial_cash=Decimal(10_000),
        costs=CostModel(),
        limits=RiskLimits(),
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )
    bot.state = BotState.RUNNING
    session.commit()
    # 상승장: 판단 → 다음 날 매수 체결까지 진행
    for bar in BARS[10:13]:
        evaluate_bot(
            session,
            bot.id,
            market=StoredMarket(),
            calendar=CAL,
            now=datetime.combine(bar.session_date, time(22, 30), tzinfo=UTC),
            trigger=Trigger.SCHEDULED,
        )
    return bot.id


def test_bot_view_shows_position_and_reason(client: TestClient, bot_id: int) -> None:
    body = client.get(f"/api/bots/{bot_id}").json()
    assert body["state"] == "RUNNING"
    assert body["account"]["qty"] > 0
    assert Decimal(body["account"]["equity"]) > 0
    assert body["account"]["last_close_date"] == BARS[-1].session_date.isoformat()
    assert body["last_decision"]["session_date"] == BARS[12].session_date.isoformat()
    assert "SMA3" in body["last_decision"]["reason"]
    assert "흐름이에요" in body["last_decision"]["plain_reason"]
    titles = [a["title"] for a in client.get("/api/activity", params={"bot_id": bot_id}).json()]
    assert any("샀어요" in t for t in titles)
    assert body["last_run"]["status"] == "OK"
    assert [b["id"] for b in client.get("/api/bots").json()] == [bot_id]
    # 체결을 다시 적용한 자산 곡선의 끝은 계좌의 지금 가치와 같다.
    curve = client.get(f"/api/bots/{bot_id}/equity").json()
    assert curve[0]["date"] == BARS[10].session_date.isoformat()
    assert Decimal(curve[-1]["equity"]) == Decimal(body["account"]["equity"])


def test_command_is_queued_for_worker(client: TestClient, session: Session, bot_id: int) -> None:
    resp = client.post(f"/api/bots/{bot_id}/commands", json={"kind": "PAUSE"})
    assert resp.status_code == 202
    assert session.scalars(select(CommandRow.kind)).all() == ["PAUSE"]

    assert client.post(f"/api/bots/{bot_id}/commands", json={"kind": "NOPE"}).status_code == 422
    assert client.post("/api/bots/999/commands", json={"kind": "START"}).status_code == 404


def test_health_reports_worker_heartbeat(client: TestClient, session: Session) -> None:
    assert client.get("/api/health").json()["worker"]["alive"] is False
    old = datetime.now(UTC) - timedelta(hours=1)
    record_heartbeat(session, "w1", "0.1.0", started_at=old, now=old)
    assert client.get("/api/health").json()["worker"]["alive"] is False  # 오래된 신호
    now = datetime.now(UTC)
    record_heartbeat(session, "w1", "0.1.0", started_at=old, now=now)  # 같은 Worker는 한 행만 갱신
    body = client.get("/api/health").json()
    assert body["db"] == "ok"
    assert body["worker"] == {
        "alive": True,
        "worker_id": "w1",
        "last_seen_at": body["worker"]["last_seen_at"],
    }


def test_run_backtest_and_list(client: TestClient, bot_id: int) -> None:
    body = {"symbol": "qqq", "strategy": "sma_cross", "params": {"fast": 3, "slow": 5}}
    created = client.post("/api/backtests", json=body)
    assert created.status_code == 201
    detail = created.json()
    assert detail["symbol"] == "QQQ" and detail["equity"]
    assert [b["id"] for b in client.get("/api/backtests").json()] == [detail["id"]]
    bad = client.post("/api/backtests", json={**body, "params": {"fast": 9, "slow": 5}})
    assert bad.status_code == 400


def test_bot_config_change_requires_pause(
    client: TestClient, session: Session, bot_id: int
) -> None:
    config = {"strategy": "trend_filter", "params": {"sma": 4}, "max_order_value": "5000"}
    assert client.put(f"/api/bots/{bot_id}/config", json=config).status_code == 409  # RUNNING

    bot = session.get_one(BotRow, bot_id)
    bot.state = BotState.PAUSED
    session.commit()
    updated = client.put(f"/api/bots/{bot_id}/config", json=config).json()
    assert updated["strategy"] == "trend_filter"
    assert updated["risk"]["max_order_value"] == "5000"
    history = client.get("/api/events", params={"bot_id": bot_id, "kind": "config_change"}).json()
    assert history[0]["data"]["before"]["strategy"] == "sma_cross"

    created = client.post(
        "/api/bots", json={"name": "voo", "symbol": "voo", "strategy": "sma_cross"}
    )
    assert created.status_code == 201 and created.json()["state"] == "STOPPED"
    assert (
        client.post(
            "/api/bots", json={"name": "voo", "symbol": "VOO", "strategy": "sma_cross"}
        ).status_code
        == 409
    )
