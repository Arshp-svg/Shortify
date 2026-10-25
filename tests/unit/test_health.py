"""Unit tests for service health endpoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_returns_200_ok() -> None:
    """Verify GET /health returns HTTP 200 with status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint_returns_metadata() -> None:
    """Verify GET / returns service metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Shortify"
    assert "version" in data
