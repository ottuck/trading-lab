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
from quant_lab.persistence.models import BotPositionRow, CommandRow
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
    assert Decimal(body["account"]["qty"]) > 0
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
    assert Decimal(curve[-1]["contributed"]) == Decimal(10_000)
    assert Decimal(curve[-1]["benchmark"]) > 0


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


def test_bot_management(client: TestClient, session: Session, bot_id: int) -> None:
    # 실행 중에도 설정을 바꾸고, 다음 판단부터 적용된다
    config = {"strategy": "trend_filter", "params": {"sma": 4}, "max_order_value": "5000"}
    updated = client.put(f"/api/bots/{bot_id}/config", json=config).json()
    assert updated["state"] == "RUNNING"
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
    assert client.patch(f"/api/bots/{bot_id}", json={"name": "voo"}).status_code == 409
    assert client.patch(f"/api/bots/{bot_id}", json={"name": "나스닥"}).json()["name"] == "나스닥"

    # 처음부터 다시 시작: 잔고·기록 초기화, 설정·상태 유지
    reset = client.post(f"/api/bots/{bot_id}/reset").json()
    assert Decimal(reset["account"]["qty"]) == 0 and reset["account"]["cash"] == "10000"
    assert reset["last_decision"] is None and reset["state"] == "RUNNING"
    assert reset["strategy"] == "trend_filter"

    voo = created.json()["id"]
    assert client.delete(f"/api/bots/{voo}").status_code == 204
    assert client.get(f"/api/bots/{voo}").status_code == 404


def test_multi_symbol_bot_rules(client: TestClient, bot_id: int) -> None:
    body = {
        "name": "me",
        "symbol": "VOO",
        "strategy": "dip_saver",
        "params": {"deposit": 675},
        "symbols": [{"symbol": "voo", "weight": 50}, {"symbol": "QQQ", "weight": 50}],
        "initial_cash": "675",
    }
    created = client.post("/api/bots", json=body).json()
    assert created["symbols"] == [{"symbol": "VOO", "weight": 50}, {"symbol": "QQQ", "weight": 50}]
    assert created["symbol"] == "VOO" and created["account"]["contributed"] == "675"
    # 비율 합이 100이 아니거나, 사고팔기 전략에 여러 종목이거나, 10개를 넘으면 막는다
    bad_sum = {
        **body,
        "name": "x",
        "symbols": [{"symbol": "VOO", "weight": 60}, {"symbol": "QQQ", "weight": 60}],
    }
    classic = {**body, "name": "y", "strategy": "sma_cross", "params": {}}
    many = {**body, "name": "z", "symbols": [{"symbol": f"S{i}", "weight": 9} for i in range(11)]}
    for bad in (bad_sum, classic, many):
        assert client.post("/api/bots", json=bad).status_code == 400


def test_change_symbols_keeps_held_ones(client: TestClient, session: Session) -> None:
    body = {
        "name": "me",
        "symbol": "VOO",
        "strategy": "dip_saver",
        "params": {"deposit": 675},
        "symbols": [{"symbol": "VOO", "weight": 50}, {"symbol": "QQQ", "weight": 50}],
        "initial_cash": "675",
    }
    bot = client.post("/api/bots", json=body).json()
    session.add(BotPositionRow(bot_id=bot["id"], symbol="VOO", qty=Decimal(1), avg_cost=500))
    session.commit()
    # 들고 있는 VOO를 빼면 비율 0으로 남아 더 사지 않고 들고만 있는다
    new = [{"symbol": "QQQ", "weight": 40}, {"symbol": "GLD", "weight": 60}]
    url = f"/api/bots/{bot['id']}/symbols"
    changed = client.put(url, json={"symbols": new}).json()
    assert changed["symbol"] == "QQQ"
    assert changed["symbols"] == [*new, {"symbol": "VOO", "weight": 0}]
    events = f"/api/events?bot_id={bot['id']}&kind=config_change"
    history = client.get(events).json()
    assert "들고만 있기: VOO" in history[0]["message"]
    assert client.put(url, json={"symbols": [{"symbol": "QQQ", "weight": 50}]}).status_code == 400


def test_parallel_worlds(client: TestClient, bot_id: int) -> None:
    # 평행세계의 나: 나, 매달 그냥 사기, 규칙을 하나씩 바꾼 나들 (저장하지 않음)
    params = {"deposit": 500, "day": 1, "dip": 10, "hot": 10, "high": 10, "sma": 5}
    body = client.post("/api/parallel", json={"symbol": "QQQ", "params": params}).json()
    worlds = {w["key"]: w for w in body["worlds"]}
    assert list(worlds)[:2] == ["me", "dca"]
    assert {"no_rest", "dip_only", "patient", "eager", "double"} <= set(worlds)
    assert Decimal(worlds["double"]["contributed"]) == 2 * Decimal(worlds["me"]["contributed"])
    assert worlds["dca"]["contributed"] == worlds["me"]["contributed"]
    assert not worlds["me"]["same_as_me"] and worlds["me"]["equity"]
    assert client.get("/api/backtests").json() == []
