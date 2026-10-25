"""Integration tests for Prometheus metrics, endpoint normalization, and structured observability."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.metrics import normalize_endpoint
from app.core.rate_limit import RateLimitResult


def test_endpoint_normalization() -> None:
    """Verify endpoint normalization maps high-cardinality paths to low-cardinality templates."""
    assert normalize_endpoint("/s0000042") == "/{short_code}"
    assert normalize_endpoint("/custom-alias-123") == "/{short_code}"
    assert normalize_endpoint("/api/v1/urls/105") == "/api/v1/urls/{id}"
    assert normalize_endpoint("/api/v1/urls/105/stats") == "/api/v1/urls/{id}/stats"
    assert normalize_endpoint("/api/v1/urls") == "/api/v1/urls"
    assert normalize_endpoint("/health") == "/health"
    assert normalize_endpoint("/ready") == "/ready"
    assert normalize_endpoint("/metrics") == "/metrics"
    assert normalize_endpoint("/docs") == "/docs"
    assert normalize_endpoint("/redoc") == "/docs"
    assert normalize_endpoint("/") == "/"


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(async_client: AsyncClient) -> None:
    """Verify GET /metrics returns valid Prometheus exposition text."""
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text
    # Verify core metric declarations exist in the scrape text
    assert "# HELP shortify_http_requests_total" in body
    assert "# TYPE shortify_http_requests_total counter" in body
    assert "# HELP shortify_http_request_duration_seconds" in body
    assert "# TYPE shortify_http_request_duration_seconds histogram" in body
    assert "# HELP shortify_in_flight_requests" in body
    assert "# TYPE shortify_in_flight_requests gauge" in body
    assert "# HELP shortify_url_operations_total" in body
    assert "# TYPE shortify_url_operations_total counter" in body
    assert "# HELP shortify_cache_operations_total" in body
    assert "# TYPE shortify_cache_operations_total counter" in body
    assert "# HELP shortify_rate_limit_rejections_total" in body
    assert "# TYPE shortify_rate_limit_rejections_total counter" in body


@pytest.mark.asyncio
async def test_metrics_track_request_lifecycle(async_client: AsyncClient) -> None:
    """Verify that creating and redirecting URLs updates HTTP and domain metrics."""
    # 1. Create short URL
    create_payload = {"original_url": "https://prometheus-test.example.com"}
    create_resp = await async_client.post("/api/v1/urls", json=create_payload)
    assert create_resp.status_code == 201
    short_code = create_resp.json()["short_code"]

    # 2. Redirect lookup
    redir_resp = await async_client.get(f"/{short_code}", follow_redirects=False)
    assert redir_resp.status_code == 307

    # 3. Scrape /metrics and verify counts
    metrics_resp = await async_client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # Verify domain operations counter
    assert 'shortify_url_operations_total{operation="create"}' in metrics_text
    assert 'shortify_url_operations_total{operation="redirect"}' in metrics_text

    # Verify normalized endpoint HTTP counters
    assert 'endpoint="/api/v1/urls"' in metrics_text
    assert 'endpoint="/{short_code}"' in metrics_text


@pytest.mark.asyncio
async def test_metrics_track_rate_limit_rejections(async_client: AsyncClient) -> None:
    """Verify that rate limit rejections increment the rate limit metric counter."""
    with patch(
        "app.core.rate_limit.RateLimiter.check_rate_limit",
        new=AsyncMock(
            return_value=RateLimitResult(
                allowed=False,
                limit=5,
                remaining=0,
                retry_after=30,
                fail_open=False,
            )
        ),
    ):
        resp = await async_client.get("/api/v1/urls", headers={"X-Forwarded-For": "10.99.99.99"})
        assert resp.status_code == 429

    metrics_resp = await async_client.get("/metrics")
    metrics_text = metrics_resp.text
    assert 'shortify_rate_limit_rejections_total{bucket="general"}' in metrics_text


@pytest.mark.asyncio
async def test_root_endpoint_includes_metrics_url(async_client: AsyncClient) -> None:
    """Verify root discovery endpoint advertises /metrics."""
    resp = await async_client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("metrics") == "/metrics"
