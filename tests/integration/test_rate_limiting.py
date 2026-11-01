"""Integration tests for Redis-backed sliding-window rate limiting."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.rate_limit import RateLimiter, RateLimitResult


@pytest.mark.asyncio
async def test_sliding_window_basic_quota(test_redis_client: Redis) -> None:
    """Verify that RateLimiter allows requests up to the limit and then rejects."""
    limiter = RateLimiter(redis_client=test_redis_client)
    ip = "192.168.1.100"
    limit = 3
    window = 60

    # First request: allowed, remaining = 2
    res1 = await limiter.check_rate_limit(client_ip=ip, bucket="test", limit=limit, window=window)
    assert res1.allowed is True
    assert res1.limit == 3
    assert res1.remaining == 2
    assert res1.retry_after == 0
    assert res1.fail_open is False

    # Second request: allowed, remaining = 1
    res2 = await limiter.check_rate_limit(client_ip=ip, bucket="test", limit=limit, window=window)
    assert res2.allowed is True
    assert res2.remaining == 1

    # Third request: allowed, remaining = 0
    res3 = await limiter.check_rate_limit(client_ip=ip, bucket="test", limit=limit, window=window)
    assert res3.allowed is True
    assert res3.remaining == 0

    # Fourth request: rejected (exceeds limit)
    res4 = await limiter.check_rate_limit(client_ip=ip, bucket="test", limit=limit, window=window)
    assert res4.allowed is False
    assert res4.remaining == 0
    assert res4.retry_after >= 1


@pytest.mark.asyncio
async def test_sliding_window_time_recovery(test_redis_client: Redis) -> None:
    """Verify that requests are allowed again once timestamps slide out of the window."""
    limiter = RateLimiter(redis_client=test_redis_client)
    ip = "192.168.1.101"
    limit = 2
    window = 1  # 1-second window for fast test

    res1 = await limiter.check_rate_limit(client_ip=ip, bucket="fast", limit=limit, window=window)
    res2 = await limiter.check_rate_limit(client_ip=ip, bucket="fast", limit=limit, window=window)
    res3 = await limiter.check_rate_limit(client_ip=ip, bucket="fast", limit=limit, window=window)
    assert res1.allowed is True
    assert res2.allowed is True
    assert res3.allowed is False

    # Wait for the 1-second window to slide past
    await asyncio.sleep(1.1)

    # Quota should have recovered
    res4 = await limiter.check_rate_limit(client_ip=ip, bucket="fast", limit=limit, window=window)
    assert res4.allowed is True
    assert res4.remaining == 1


@pytest.mark.asyncio
async def test_multi_client_ip_isolation(test_redis_client: Redis) -> None:
    """Verify that rate limits for separate client IPs do not cross-contaminate."""
    limiter = RateLimiter(redis_client=test_redis_client)
    ip_a = "10.0.0.1"
    ip_b = "10.0.0.2"
    limit = 2
    window = 60

    # Exhaust IP A
    await limiter.check_rate_limit(client_ip=ip_a, bucket="iso", limit=limit, window=window)
    await limiter.check_rate_limit(client_ip=ip_a, bucket="iso", limit=limit, window=window)
    res_a_exhausted = await limiter.check_rate_limit(
        client_ip=ip_a, bucket="iso", limit=limit, window=window
    )
    assert res_a_exhausted.allowed is False

    # IP B should still have full quota
    res_b = await limiter.check_rate_limit(client_ip=ip_b, bucket="iso", limit=limit, window=window)
    assert res_b.allowed is True
    assert res_b.remaining == 1


@pytest.mark.asyncio
async def test_rate_limiter_fail_open_on_redis_error() -> None:
    """Verify that Redis connection errors result in fail-open permission."""
    mock_redis = AsyncMock(spec=Redis)
    mock_redis.eval.side_effect = RedisConnectionError("Redis connection refused")

    limiter = RateLimiter(redis_client=mock_redis)
    result = await limiter.check_rate_limit(
        client_ip="192.168.1.102", bucket="failopen", limit=10, window=60
    )

    assert result.allowed is True
    assert result.fail_open is True
    assert result.remaining == 10
    assert result.retry_after == 0


@pytest.mark.asyncio
async def test_http_rate_limit_headers_on_success(async_client: AsyncClient) -> None:
    """Verify HTTP responses contain standard X-RateLimit headers."""
    # Use a unique IP via X-Forwarded-For
    headers = {"X-Forwarded-For": "203.0.113.10"}
    response = await async_client.get("/api/v1/urls", headers=headers)

    # Endpoint might return 200 or 404 depending on URLs, but middleware headers must exist
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers


@pytest.mark.asyncio
async def test_http_rate_limit_exceeded_returns_429(async_client: AsyncClient) -> None:
    """Verify that exceeding rate limit returns HTTP 429 with Retry-After and standard error body."""
    headers = {"X-Forwarded-For": "203.0.113.42"}

    # Mock the rate limiter to return rejected
    with patch(
        "app.core.rate_limit.RateLimiter.check_rate_limit",
        new=AsyncMock(
            return_value=RateLimitResult(
                allowed=False,
                limit=5,
                remaining=0,
                retry_after=15,
                fail_open=False,
            )
        ),
    ):
        response = await async_client.get("/api/v1/urls", headers=headers)

        assert response.status_code == 429
        assert response.headers["retry-after"] == "15"
        assert response.headers["x-ratelimit-limit"] == "5"
        assert response.headers["x-ratelimit-remaining"] == "0"
        assert response.headers["x-ratelimit-reset"] == "15"
        assert "x-request-id" in response.headers

        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "15 seconds" in body["error"]["message"]
        assert body["error"]["details"][0]["retry_after"] == 15


@pytest.mark.asyncio
async def test_exempt_paths_bypass_rate_limiting(async_client: AsyncClient) -> None:
    """Verify health and docs endpoints are never rate limited."""
    # Call health check 10 times with arbitrary IP
    headers = {"X-Forwarded-For": "203.0.113.99"}
    for _ in range(10):
        response = await async_client.get("/health", headers=headers)
        assert response.status_code == 200
        # Exempt routes should not have rate limit headers injected
        assert "x-ratelimit-limit" not in response.headers
