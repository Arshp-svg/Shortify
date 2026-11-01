"""Resilience and fault-injection automated tests.

Verifies:
1. Redis Outage: Fail-open fallback to PostgreSQL for redirects (0% 500 errors)
2. Redis Outage: Fail-open rate limiting bypass with X-RateLimit-FailOpen header
3. PostgreSQL Outage: Graceful HTTP 503 Service Unavailable with standard error JSON
4. DB Pool Saturation: Graceful HTTP 503 on connection pool timeout
5. Readiness Probe: Accurately reflects database and cache operational health
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from sqlalchemy.exc import OperationalError, TimeoutError

from app.core.rate_limit import RateLimiter
from app.services.cache_service import CacheService


@pytest.mark.asyncio
async def test_redis_outage_redirect_fail_open(async_client: AsyncClient) -> None:
    """Verify that when Redis fails during redirect lookup, API falls back to PostgreSQL seamlessly."""
    # 1. Create a URL in the database
    create_resp = await async_client.post(
        "/api/v1/urls", json={"original_url": "https://failopen-resilience.example.com"}
    )
    assert create_resp.status_code == 201
    short_code = create_resp.json()["short_code"]

    # 2. Simulate complete Redis outage on cache service
    failing_cache = CacheService(
        redis_client=AsyncMock(),
        default_ttl=3600,
        fail_open=True,
        enabled=True,
    )
    failing_cache.get_url = AsyncMock(side_effect=RedisError("Redis connection dropped"))  # type: ignore[method-assign]

    with patch("app.api.deps.get_cache_service", return_value=failing_cache):
        # Request redirect: must NOT fail with 500; must fall back to PostgreSQL and return 307
        resp = await async_client.get(f"/{short_code}", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "https://failopen-resilience.example.com/"


@pytest.mark.asyncio
async def test_redis_outage_rate_limit_fail_open(async_client: AsyncClient) -> None:
    """Verify rate limiter fails open with X-RateLimit-FailOpen header when Redis is unreachable."""
    # When RateLimiter encounters Redis error, check_rate_limit catches it and returns fail_open=True
    with patch(
        "app.core.rate_limit.get_rate_limiter",
        return_value=RateLimiter(
            redis_client=AsyncMock(eval=AsyncMock(side_effect=RedisConnectionError("Redis down")))
        ),
    ):
        resp = await async_client.get("/s0000001", follow_redirects=False)
        assert resp.status_code in (307, 404)
        assert resp.headers.get("x-ratelimit-failopen") == "true"


@pytest.mark.asyncio
async def test_postgres_outage_returns_503(async_client: AsyncClient) -> None:
    """Verify that database connection failures return structured HTTP 503 Service Unavailable."""
    # Simulate DB OperationalError (e.g. host unreachable or connection refused)
    with patch(
        "app.repositories.url_repository.URLRepository.create",
        side_effect=OperationalError("Connection lost", None, Exception("Postgres unreachable")),
    ):
        resp = await async_client.post(
            "/api/v1/urls", json={"original_url": "https://postgres-down.example.com"}
        )
        assert resp.status_code == 503
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "DATABASE_UNAVAILABLE"
        assert "unavailable" in body["error"]["message"].lower()


@pytest.mark.asyncio
async def test_postgres_pool_timeout_returns_503(async_client: AsyncClient) -> None:
    """Verify that connection pool exhaustion returns structured HTTP 503 Service Unavailable."""
    with patch(
        "app.repositories.url_repository.URLRepository.get_by_short_code",
        side_effect=TimeoutError("QueuePool limit exceeded", None, None),
    ):
        resp = await async_client.get("/s0000001", follow_redirects=False)
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "DATABASE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_readiness_probe_degraded_when_postgres_down(async_client: AsyncClient) -> None:
    """Verify /ready probe returns 503 and reports unready when PostgreSQL is unreachable."""
    mock_db = AsyncMock()
    mock_db.execute.side_effect = OperationalError("connection down", None, Exception("down"))

    from app.api.deps import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        resp = await async_client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unready"
        assert "disconnected" in data["checks"]["database"]
    finally:
        app.dependency_overrides.pop(get_db, None)
