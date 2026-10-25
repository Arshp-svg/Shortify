"""Unit tests for centralized error handling and response envelopes."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    EntityConflictException,
    EntityExpiredException,
    EntityNotFoundException,
    register_exception_handlers,
)

sample_app = FastAPI()
register_exception_handlers(sample_app)


@sample_app.get("/trigger-404")
def trigger_404() -> None:
    raise EntityNotFoundException("Test short code not found", code="URL_NOT_FOUND")


@sample_app.get("/trigger-409")
def trigger_409() -> None:
    raise EntityConflictException("Test alias collision", code="ALIAS_CONFLICT")


@sample_app.get("/trigger-410")
def trigger_410() -> None:
    raise EntityExpiredException("Test URL has expired", code="URL_EXPIRED")


@sample_app.get("/trigger-500")
def trigger_500() -> None:
    raise RuntimeError("Unexpected boom")


client = TestClient(sample_app, raise_server_exceptions=False)


def test_404_error_envelope() -> None:
    """Verify 404 response matches standard envelope."""
    response = client.get("/trigger-404")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "URL_NOT_FOUND"
    assert data["error"]["message"] == "Test short code not found"
    assert "request_id" in data["error"]


def test_409_conflict_envelope() -> None:
    """Verify 409 response matches standard envelope."""
    response = client.get("/trigger-409")
    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "ALIAS_CONFLICT"


def test_410_expired_envelope() -> None:
    """Verify 410 response matches standard envelope."""
    response = client.get("/trigger-410")
    assert response.status_code == 410
    data = response.json()
    assert data["error"]["code"] == "URL_EXPIRED"


def test_500_internal_error_does_not_leak_trace() -> None:
    """Verify 500 error sanitizes error message and hides stack trace."""
    response = client.get("/trigger-500")
    assert response.status_code == 500
    data = response.json()
    assert data["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "boom" not in data["error"]["message"]
