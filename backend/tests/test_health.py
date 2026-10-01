from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from quant_lab.api.main import app
from quant_lab.persistence.db import get_session
from quant_lab.persistence.heartbeat import record_heartbeat


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_without_worker(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] == "ok"
    assert body["worker"]["alive"] is False
    assert body["worker"]["worker_id"] is None


def test_health_with_recent_heartbeat(client: TestClient, session: Session) -> None:
    now = datetime.now(UTC)
    record_heartbeat(session, "w1", "0.1.0", started_at=now, now=now)
    body = client.get("/api/health").json()
    assert body["worker"]["alive"] is True
    assert body["worker"]["worker_id"] == "w1"


def test_health_with_stale_heartbeat(client: TestClient, session: Session) -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    record_heartbeat(session, "w1", "0.1.0", started_at=old, now=old)
    assert client.get("/api/health").json()["worker"]["alive"] is False
