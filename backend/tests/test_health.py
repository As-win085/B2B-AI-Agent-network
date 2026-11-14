from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_liveness_root_is_plain() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Asama.ai API"
    assert "data" not in body


def test_liveness_versioned_is_enveloped() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert "status" not in body


def test_meta_root_is_plain() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["health"] == "/health"
