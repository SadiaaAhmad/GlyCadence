from fastapi.testclient import TestClient

from app.api import health as health_api
from app.main import app

client = TestClient(app)


def test_get_health_returns_ok() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "GlyCadence API"
    assert "timestamp" in body


def test_get_health_db_connected(monkeypatch) -> None:
    monkeypatch.setattr(health_api, "check_db_connection", lambda: (True, 15, "connected"))
    response = client.get("/api/v1/health/db")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["detected_major_version"] == 15


def test_get_health_db_unavailable_does_not_leak_internals(monkeypatch) -> None:
    monkeypatch.setattr(health_api, "check_db_connection", lambda: (False, None, "database_unavailable"))
    response = client.get("/api/v1/health/db")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "database_unavailable"
    assert body["detected_major_version"] is None
    assert "password" not in response.text.lower()
    assert "psycopg" not in response.text.lower()
