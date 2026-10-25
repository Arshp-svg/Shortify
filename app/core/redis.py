"""Async Redis connection management and health monitoring."""

import asyncio
import contextlib
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_redis_pool: ConnectionPool | None = None
_redis_client: aioredis.Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def get_redis_client() -> aioredis.Redis:
    """Retrieve or initialize the active async Redis client bound to the current event loop."""
    global _redis_client, _redis_pool, _redis_loop

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    # Re-initialize if client is None or if running in a new event loop (e.g. pytest-asyncio on Windows)
    if _redis_client is None or _redis_loop != current_loop:
        _redis_loop = current_loop
        settings = get_settings()
        _redis_pool = ConnectionPool.from_url(
            settings.redis_url,
            max_connections=50,
            socket_timeout=settings.redis_timeout_seconds,
            socket_connect_timeout=settings.redis_timeout_seconds,
            decode_responses=True,
        )
        _redis_client = aioredis.Redis(connection_pool=_redis_pool)
        logger.info(
            "Initialized Redis client for %s:%d (event loop %s)",
            settings.redis_host,
            settings.redis_port,
            id(current_loop) if current_loop else "none",
        )

    return _redis_client


async def close_redis() -> None:
    """Gracefully close the Redis client and connection pool."""
    global _redis_client, _redis_pool, _redis_loop
    if _redis_client is not None:
        with contextlib.suppress(Exception):
            await _redis_client.close()
        _redis_client = None
    if _redis_pool is not None:
        with contextlib.suppress(Exception):
            await _redis_pool.disconnect()
        _redis_pool = None
    _redis_loop = None
    logger.info("Closed Redis connection pool.")


async def check_redis_health() -> dict[str, Any]:
    """Execute a PING probe to determine Redis reachability and latency."""
    client = get_redis_client()
    try:
        import time

        start = time.perf_counter()
        res = await client.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "healthy" if res else "unhealthy",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        logger.warning("Redis healthcheck failed: %s", exc)
        return {
            "status": "unhealthy",
            "error": str(exc),
        }
