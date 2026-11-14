"""ASAMA-101: canonical API response envelope and request correlation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import AppError
from app.core.responses import success
from app.main import app, create_app

client = TestClient(app)


class _Payload(BaseModel):
    name: str


def _app_with_validation_route() -> FastAPI:
    test_app = create_app()

    @test_app.post("/api/v1/_test/validate")
    def _validate(payload: _Payload) -> dict:
        return success(payload.model_dump())

    return test_app


def test_success_envelope_echoes_caller_request_id() -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req-caller-1"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-caller-1"
    assert response.json()["data"]["status"] == "ok"


def test_success_envelope_generates_request_id() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) == 36  # UUID4


def test_unsafe_request_id_is_replaced() -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id with spaces"})
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert request_id != "bad id with spaces"


def test_unknown_route_returns_error_envelope() -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["message"]


def test_method_not_allowed_returns_error_envelope() -> None:
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_validation_error_returns_field_details() -> None:
    test_client = TestClient(_app_with_validation_route())
    response = test_client.post("/api/v1/_test/validate", json={})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert error["details"][0]["field"] == "body.name"
    assert error["details"][0]["type"] == "missing"


def test_app_error_uses_canonical_envelope() -> None:
    test_app = create_app()

    @test_app.get("/api/v1/_test/app-error")
    def _raise_app_error() -> None:
        raise AppError(
            "Organization already exists.",
            code="organization_exists",
            status_code=409,
            details=[{"field": "slug"}],
        )

    test_client = TestClient(test_app)
    response = test_client.get("/api/v1/_test/app-error")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "organization_exists"
    assert error["details"] == [{"field": "slug"}]


def test_unhandled_error_hides_internals() -> None:
    test_app = create_app()

    @test_app.get("/api/v1/_test/boom")
    def _boom() -> None:
        raise RuntimeError("secret connection string")

    test_client = TestClient(test_app, raise_server_exceptions=False)
    response = test_client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "internal_error"
    assert error["message"] == "An unexpected error occurred."
    assert "secret" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_success_helper_adds_optional_meta() -> None:
    assert success([1, 2]) == {"data": [1, 2]}
    assert success([1, 2], meta={"page": 1}) == {"data": [1, 2], "meta": {"page": 1}}
