"""Unit tests for service health, readiness, and request correlation headers."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app

client = TestClient(app)


def test_health_check_returns_200_ok() -> None:
    """Verify GET /health returns HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Request-ID" in response.headers


def test_root_endpoint_returns_metadata() -> None:
    """Verify GET / returns service metadata and links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Shortify"
    assert "version" in data
    assert "health" in data
    assert "ready" in data


def test_ready_endpoint_healthy() -> None:
    """Verify GET /ready returns 200 when database responds cleanly."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=None)

    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["checks"]["database"] == "connected"
    finally:
        app.dependency_overrides.clear()


def test_ready_endpoint_unhealthy() -> None:
    """Verify GET /ready returns 503 when database connection fails."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=ConnectionRefusedError("Database unreachable"))

    async def override_get_db() -> AsyncGenerator[AsyncMock, None]:
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unready"
        assert "disconnected" in data["checks"]["database"]
    finally:
        app.dependency_overrides.clear()


def test_request_id_custom_propagation() -> None:
    """Verify that incoming X-Request-ID header is echoed back."""
    custom_id = "test-custom-req-id-12345"
    response = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_id
