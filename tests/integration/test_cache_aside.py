"""Integration tests for Redis Cache-Aside pattern, invalidation, TTL, and fail-open resilience."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.exceptions import EntityExpiredException
from app.repositories.url_repository import URLRepository
from app.schemas.url import URLCreateRequest
from app.services.cache_service import CacheService
from app.services.url_service import URLService


@pytest.mark.asyncio
async def test_cache_aside_miss_then_hit(
    db_session: Any, clean_urls_table: None, test_redis_client: Any
) -> None:
    """Verify cache miss falls through to DB, populates Redis, and subsequent call hits cache."""
    repo = URLRepository(db_session)
    cache = CacheService(redis_client=test_redis_client, default_ttl=300)
    service = URLService(repository=repo, base_url="http://short.ly", cache_service=cache)

    # 1. Create a URL record directly in DB
    created = await service.create_url(
        URLCreateRequest(
            original_url="https://docs.fastapi.tiangolo.com",
            custom_alias="fastapi",
        )
    )
    assert created.short_code == "fastapi"

    # 2. Assert Redis has no entry yet (pure cache-aside on read)
    cached_val_before = await test_redis_client.get("url:fastapi")
    assert cached_val_before is None

    # 3. First read: Cache Miss -> Populates Redis
    dest_1 = await service.resolve_redirect("fastapi")
    assert dest_1 == "https://docs.fastapi.tiangolo.com/"

    # 4. Assert key is now populated in Redis
    cached_val_after = await test_redis_client.get("url:fastapi")
    assert cached_val_after == "https://docs.fastapi.tiangolo.com/"
    assert cache._local_misses == 1
    assert cache._local_hits == 0

    # 5. Second read: Cache Hit
    dest_2 = await service.resolve_redirect("fastapi")
    assert dest_2 == "https://docs.fastapi.tiangolo.com/"
    assert cache._local_hits == 1


@pytest.mark.asyncio
async def test_cache_invalidation_on_soft_delete(
    db_session: Any, clean_urls_table: None, test_redis_client: Any
) -> None:
    """Verify that deleting/deactivating a URL immediately removes its key from Redis."""
    repo = URLRepository(db_session)
    cache = CacheService(redis_client=test_redis_client, default_ttl=300)
    service = URLService(repository=repo, base_url="http://short.ly", cache_service=cache)

    created = await service.create_url(
        URLCreateRequest(
            original_url="https://pytest.org",
            custom_alias="pytest",
        )
    )

    # Prime cache via first read
    await service.resolve_redirect("pytest")
    assert await test_redis_client.get("url:pytest") == "https://pytest.org/"

    # Soft delete URL
    await service.delete_url(created.id)

    # Assert Redis key is immediately evicted
    cached_after_delete = await test_redis_client.get("url:pytest")
    assert cached_after_delete is None

    # Subsequent redirect attempt raises EntityExpiredException
    with pytest.raises(EntityExpiredException):
        await service.resolve_redirect("pytest")


@pytest.mark.asyncio
async def test_cache_ttl_on_expiring_url(
    db_session: Any, clean_urls_table: None, test_redis_client: Any
) -> None:
    """Verify cache entry TTL is bounded by remaining expiration time."""
    repo = URLRepository(db_session)
    cache = CacheService(redis_client=test_redis_client, default_ttl=3600)
    service = URLService(repository=repo, base_url="http://short.ly", cache_service=cache)

    expires = datetime.now(UTC) + timedelta(seconds=20)
    await service.create_url(
        URLCreateRequest(
            original_url="https://temporary.example.com",
            custom_alias="temp20",
            expires_at=expires,
        )
    )

    # Prime cache
    await service.resolve_redirect("temp20")

    # Check TTL in Redis
    ttl = await test_redis_client.ttl("url:temp20")
    # TTL should be roughly 19-20 seconds, strictly <= 20
    assert 0 < ttl <= 20


@pytest.mark.asyncio
async def test_fail_open_on_redis_error(db_session: Any, clean_urls_table: None) -> None:
    """Verify that when Redis throws errors, fail-open policy serves the request via PostgreSQL."""
    repo = URLRepository(db_session)

    # Create mock Redis client that raises RedisConnectionError on any call
    broken_redis = AsyncMock()
    broken_redis.get.side_effect = RedisConnectionError("Connection refused to Redis")
    broken_redis.set.side_effect = RedisConnectionError("Connection refused to Redis")
    broken_redis.delete.side_effect = RedisConnectionError("Connection refused to Redis")
    broken_redis.incr.side_effect = RedisConnectionError("Connection refused to Redis")

    cache = CacheService(redis_client=broken_redis, default_ttl=300, fail_open=True)
    service = URLService(repository=repo, base_url="http://short.ly", cache_service=cache)

    await service.create_url(
        URLCreateRequest(
            original_url="https://resilience-target.example.com",
            custom_alias="failopen",
        )
    )

    # Despite broken Redis, resolve_redirect should NOT throw an error; it should fall back to DB
    destination = await service.resolve_redirect("failopen")
    assert destination == "https://resilience-target.example.com/"
    assert cache._local_errors >= 1


@pytest.mark.asyncio
async def test_fail_open_http_endpoint(
    async_client: Any, clean_urls_table: None, db_session: Any
) -> None:
    """Test full HTTP API redirect flow when Redis cache is disabled or failed."""
    repo = URLRepository(db_session)
    await repo.create(
        original_url="https://http-resilience.example.com",
        short_code="httpres",
    )

    # Request redirect via HTTP client
    resp = await async_client.get("/httpres", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "https://http-resilience.example.com"
    assert "no-cache" in resp.headers["cache-control"]
