import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.fakes import WeekdayCalendar, make_bars
from trading_lab.api.main import app
from trading_lab.application.dry_run import Trigger, evaluate_bot
from trading_lab.application.market import StoredMarket
from trading_lab.domain.bot import BotState
from trading_lab.domain.portfolio import CostModel, RiskLimits
from trading_lab.domain.strategy import DipSaver
from trading_lab.persistence.bars import upsert_daily_bars
from trading_lab.persistence.bots import create_bot
from trading_lab.persistence.db import get_session
from trading_lab.persistence.heartbeat import record_heartbeat
from trading_lab.persistence.models import BotPositionRow, BotRow, CommandRow, LiveOrderRow, RunRow

CAL = WeekdayCalendar()
BARS = make_bars("QQQ", [100 + i for i in range(30)])
RULE = {"deposit": 500, "day": 1, "dip": 10, "hot": 10, "high": 10, "sma": 5}


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
        strategy="dip_saver",
        params=DipSaver(**RULE).params,
        initial_cash=Decimal(500),
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
    assert "SMA5" in body["last_decision"]["reason"]
    assert "적당한 가격" in body["last_decision"]["plain_reason"]
    titles = [a["title"] for a in client.get("/api/activity", params={"bot_id": bot_id}).json()]
    assert any("샀어요" in t for t in titles)
    assert body["last_run"]["status"] == "OK"
    assert [b["id"] for b in client.get("/api/bots").json()] == [bot_id]
    # 체결을 다시 적용한 자산 곡선의 끝은 계좌의 지금 가치와 같다.
    curve = client.get(f"/api/bots/{bot_id}/equity").json()
    assert curve[0]["date"] == BARS[10].session_date.isoformat()
    assert Decimal(curve[-1]["equity"]) == Decimal(body["account"]["equity"])
    assert Decimal(curve[-1]["contributed"]) == Decimal(500)
    assert Decimal(curve[-1]["benchmark"]) > 0


def test_command_is_queued_for_worker(client: TestClient, session: Session, bot_id: int) -> None:
    resp = client.post(f"/api/bots/{bot_id}/commands", json={"kind": "PAUSE"})
    assert resp.status_code == 202
    assert session.scalars(select(CommandRow.kind)).all() == ["PAUSE"]
    # 처리 전에는 화면이 "멈추는 중"으로 보인다
    assert client.get(f"/api/bots/{bot_id}").json()["pending_command"] == "PAUSE"

    assert client.post(f"/api/bots/{bot_id}/commands", json={"kind": "NOPE"}).status_code == 422
    assert client.post("/api/bots/999/commands", json={"kind": "START"}).status_code == 404


def test_health_says_bots_are_evaluating_only_for_recent_running_runs(
    client: TestClient, session: Session
) -> None:
    """배포가 판단 중에 Worker를 다시 띄우지 않도록 묻는 값. 옛 기록은 무시한다."""
    now = datetime.now(UTC)
    assert client.get("/api/health").json()["evaluating"] is False
    bot = create_bot(
        session, name="t", symbol="QQQ", strategy="dip_saver", params=DipSaver(**RULE).params,
        initial_cash=Decimal(500), costs=CostModel(), limits=RiskLimits(), now=now,
    )  # fmt: skip
    old = RunRow(id=uuid.uuid4(), bot_id=bot.id, trigger="SCHEDULED", status="RUNNING",
                 started_at=now - timedelta(hours=2))  # fmt: skip
    session.add(old)
    session.commit()
    assert client.get("/api/health").json()["evaluating"] is False
    old.started_at = now - timedelta(minutes=2)
    session.commit()
    assert client.get("/api/health").json()["evaluating"] is True


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
    body = {"symbol": "qqq", "strategy": "dip_saver", "params": RULE}
    created = client.post("/api/backtests", json=body)
    assert created.status_code == 201
    detail = created.json()
    assert detail["symbol"] == "QQQ" and detail["equity"]
    assert [b["id"] for b in client.get("/api/backtests").json()] == [detail["id"]]
    # 같은 조건으로 다시 시험하면 새 결과 하나만 남는다
    again = client.post("/api/backtests", json=body).json()
    assert [b["id"] for b in client.get("/api/backtests").json()] == [again["id"]]
    bad = client.post("/api/backtests", json={**body, "params": {"deposit": 0}})
    assert bad.status_code == 400


def test_bot_management(client: TestClient, session: Session, bot_id: int) -> None:
    # 실행 중에도 설정을 바꾸고, 다음 판단부터 적용된다
    config = {"strategy": "dip_saver", "params": {**RULE, "dip": 15}, "max_order_value": "5000"}
    updated = client.put(f"/api/bots/{bot_id}/config", json=config).json()
    assert updated["state"] == "RUNNING"
    assert updated["params"]["dip"] == 15
    assert updated["risk"]["max_order_value"] == "5000"
    history = client.get("/api/events", params={"bot_id": bot_id, "kind": "config_change"}).json()
    assert history[0]["data"]["before"]["params"]["dip"] == 10
    # 바꾼 기록은 무엇을 바꿨는지 쉬운 말로
    (change,) = client.get(
        "/api/activity", params={"bot_id": bot_id, "kind": "config_change"}
    ).json()
    assert change["body"] == "하락장 기준 -10% → -15%"
    # 최대 투자 금액 0(아예 못 삼)과 너무 긴 이름은 막는다
    zero = {**config, "max_position_value": "0"}
    assert client.put(f"/api/bots/{bot_id}/config", json=zero).status_code == 400
    assert client.patch(f"/api/bots/{bot_id}", json={"name": "가" * 21}).status_code == 400
    # 한 자리 더 친 금액은 만들 때 막는다 (시작 금액 $1,000,000·매달 $100,000까지)
    big = {"name": "큰돈", "symbol": "voo", "strategy": "dip_saver", "initial_cash": "2000000"}
    assert client.post("/api/bots", json=big).status_code == 400
    deposit = {
        "name": "큰달",
        "symbol": "voo",
        "strategy": "dip_saver",
        "params": {"deposit": 500000},
    }
    assert client.post("/api/bots", json=deposit).status_code == 400
    # 나 카피 봇·AI 봇은 전략마다 하나만 (같은 전략의 두 번째는 이름이 달라도 막는다)
    me = {"name": "나 카피 봇 2", "symbol": "voo", "strategy": "dip_saver"}
    assert client.post("/api/bots", json=me).status_code == 409  # bot_id가 이미 나 카피 봇
    ai = {"name": "voo", "symbol": "voo", "strategy": "ai_judge"}
    created = client.post("/api/bots", json=ai)
    assert created.status_code == 201 and created.json()["state"] == "STOPPED"
    assert client.post("/api/bots", json={**ai, "name": "AI 2"}).status_code == 409
    assert client.post("/api/bots", json=ai).status_code == 409
    assert client.patch(f"/api/bots/{bot_id}", json={"name": "voo"}).status_code == 409
    assert client.patch(f"/api/bots/{bot_id}", json={"name": "나스닥"}).json()["name"] == "나스닥"

    # 처음부터 다시 시작: 잔고·기록 초기화, 설정·상태 유지
    reset = client.post(f"/api/bots/{bot_id}/reset").json()
    assert Decimal(reset["account"]["qty"]) == 0 and reset["account"]["cash"] == "500"
    assert reset["last_decision"] is None and reset["state"] == "RUNNING"
    assert reset["params"]["dip"] == 15
    kinds: dict[str, str | int] = {"bot_id": bot_id, "kind": "config_change"}
    assert len(client.get("/api/activity", params=kinds).json()) == 2  # 설정 기록은 남긴다

    ai_id = created.json()["id"]
    assert client.delete(f"/api/bots/{ai_id}").status_code == 204
    assert client.get(f"/api/bots/{ai_id}").status_code == 404


def test_multi_symbol_bot_rules(client: TestClient, session: Session) -> None:
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
    # 비율 합이 100이 아니거나 10개를 넘으면 막는다
    bad_sum = {
        **body,
        "name": "x",
        "symbols": [{"symbol": "VOO", "weight": 60}, {"symbol": "QQQ", "weight": 60}],
    }
    many = {**body, "name": "z", "symbols": [{"symbol": f"S{i}", "weight": 9} for i in range(11)]}
    for bad in (bad_sum, many):
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
    assert set(worlds) == {"me", "dca", "no_rest", "dip_only", "patient", "eager", "double"}
    assert {w["contributed"] for w in worlds.values()} == {worlds["me"]["contributed"]}
    # 2배 종목을 산 나: 규칙은 같고 종목만 달라 바꿀 수 없다 (params 없음)
    assert worlds["double"]["params"] is None
    assert worlds["double"]["final_equity"] != worlds["me"]["final_equity"]
    assert not worlds["me"]["same_as_me"] and worlds["me"]["equity"]
    # 그래프는 넣은 돈 대비로 그리므로 점마다 그날까지 넣은 돈이 있다
    assert worlds["me"]["equity"][-1]["contributed"] == worlds["me"]["contributed"]
    # 월간 정리: 지난달·이번 달에 산 금액 (매달 그냥 사기는 넣은 만큼 산다)
    assert [len(w["recent"]) for w in worlds.values()] == [2] * len(worlds)
    assert sum(Decimal(r["bought"]) for r in worlds["me"]["recent"]) > 0
    assert client.get("/api/backtests").json() == []


def test_cloudflare_access_guard(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # 도메인(Cloudflare, cf-ray 헤더)으로 온 요청은 Access 토큰이 있어야 한다. Tailscale은 그대로
    from cryptography.hazmat.primitives.asymmetric import rsa

    from trading_lab.api import main
    from trading_lab.api.access import AccessGuard

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    guard = AccessGuard("me", "aud-tag")
    signing = type("Key", (), {"key": key.public_key()})()
    monkeypatch.setattr(guard.jwks, "get_signing_key_from_jwt", lambda _token: signing)
    monkeypatch.setattr(main, "access", guard)
    claims = {"aud": "aud-tag", "iss": guard.issuer, "email": "me@example.com"}
    good = jwt.encode(claims, key, algorithm="RS256")
    bad = jwt.encode({**claims, "aud": "other"}, key, algorithm="RS256")

    cf = {"cf-ray": "1"}
    assert client.get("/api/strategies").status_code == 200  # Tailscale
    assert client.get("/api/strategies", headers=cf).status_code == 403
    assert (
        client.get("/api/strategies", headers={**cf, "cf-access-jwt-assertion": bad}).status_code
        == 403
    )
    ok = client.get("/api/strategies", headers={**cf, "cf-access-jwt-assertion": good})
    assert ok.status_code == 200


def test_follow_plan(client: TestClient, session: Session) -> None:
    # 따라 하기: 다음 입금일·종목별로 살 금액·조건 가격 (지금 가격이 이어진다면)
    upsert_daily_bars(session, BARS, "test", datetime(2026, 1, 1, tzinfo=UTC))
    params = {"deposit": 500, "day": 1, "dip": 10, "hot": 10, "high": 10, "sma": 5}
    body = {"name": "me", "symbol": "QQQ", "strategy": "dip_saver", "params": params}
    me = client.post("/api/bots", json={**body, "initial_cash": "500"}).json()
    plan = client.get(f"/api/bots/{me['id']}/plan").json()
    assert plan["deposit_date"] > plan["as_of"] and plan["deposit"] == "500"
    (qqq,) = plan["symbols"]
    assert Decimal(qqq["dip_price"]) < Decimal(qqq["close"])
    assert Decimal(qqq["buy"]) + Decimal(qqq["save"]) > 0

    # 첫 판단: 시작 금액으로 다음 장에 살 예정. 그 돈은 이미 쓴 것이라 입금일에는 그달 입금만 산다.
    # 시작 금액이 시작한 달의 입금이라 다음 입금일은 다음 달이다.
    bot = client.get(f"/api/bots/{me['id']}").json()
    session.get_one(BotRow, me["id"]).state = BotState.RUNNING
    session.commit()
    evaluate_bot(
        session,
        me["id"],
        market=StoredMarket(),
        calendar=CAL,
        now=datetime.combine(BARS[-1].session_date, time(22, 30), tzinfo=UTC),
        trigger=Trigger.SCHEDULED,
    )
    assert client.get(f"/api/bots/{me['id']}").json()["pending_orders"]
    plan = client.get(f"/api/bots/{me['id']}/plan").json()
    (qqq,) = plan["symbols"]
    assert Decimal(qqq["buy"]) == Decimal(500) and bot["account"]["contributed"] == "500"
    assert plan["deposit_date"][:7] > plan["as_of"][:7]


def test_demo_mode_is_read_only(
    client: TestClient, bot_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 데모(D2): 보기·계산은 되고, 봇 만들기·명령·설정 바꾸기는 막는다
    from trading_lab.api import main

    monkeypatch.setattr(main._settings, "demo_mode", True)
    assert client.get("/api/health").json()["demo"] is True
    assert client.get("/api/bots").status_code == 200
    params = {"deposit": 500, "day": 1, "dip": 10, "hot": 10, "high": 10, "sma": 5}
    assert client.post("/api/parallel", json={"symbol": "QQQ", "params": params}).status_code == 200
    assert client.post(f"/api/bots/{bot_id}/commands", json={"kind": "STOP"}).status_code == 403
    assert client.delete(f"/api/bots/{bot_id}").status_code == 403
    assert (
        client.post(
            "/api/live-orders/1/resolve", json={"confirmed": True, "broker_order_id": None}
        ).status_code
        == 403
    )


def test_unknown_resolution_requires_confirmation_and_never_marks_a_hint_as_sent(
    client: TestClient, session: Session
) -> None:
    now = datetime(2026, 10, 2, 13, 35, tzinfo=UTC)
    order = LiveOrderRow(
        symbol="VOO", signal_date=now.date(), trade_date=now.date(), amount=Decimal(10),
        key="unknown-api", state="UNKNOWN", source="test", sent_at=now,
        created_at=now, updated_at=now,
    )  # fmt: skip
    session.add(order)
    session.commit()
    route = f"/api/live-orders/{order.id}/resolve"
    assert client.get("/api/live").json()["unknown_order_ids"] == [order.id]
    assert client.post(route, json={"broker_order_id": None}).status_code == 422
    assert client.post(route, json={"confirmed": False, "broker_order_id": None}).status_code == 422
    assert client.post(route, json={"confirmed": True, "broker_order_id": "  "}).status_code == 400
    response = client.post(route, json={"confirmed": True, "broker_order_id": "broker-id"})
    assert response.status_code == 200
    assert response.json()["unknown_order_ids"] == [order.id]
    assert response.json()["orders"][0]["state"] == "UNKNOWN"
    assert (
        client.post(route, json={"confirmed": True, "broker_order_id": None}).json()[
            "unknown_order_ids"
        ]
        == []
    )
    assert client.post(route, json={"confirmed": True, "broker_order_id": None}).status_code == 409
