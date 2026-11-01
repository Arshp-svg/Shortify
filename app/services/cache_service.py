"""Redis cache-aside service with fail-open resilience and TTL management."""

import logging
import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.metrics import record_cache_operation

logger = logging.getLogger(__name__)


class CacheService:
    """Async Redis Cache-Aside service for URL redirect lookups."""

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        default_ttl: int = 3600,
        fail_open: bool = True,
        enabled: bool = True,
    ) -> None:
        self.redis = redis_client
        self.default_ttl = default_ttl
        self.fail_open = fail_open
        self.enabled = enabled
        self._local_hits: int = 0
        self._local_misses: int = 0
        self._local_errors: int = 0
        self._circuit_open_until: float = 0.0
        self._circuit_break_duration: float = 3.0

    @property
    def is_available(self) -> bool:
        """Indicate whether caching is enabled, client configured, and circuit is not open."""
        if not self.enabled or self.redis is None:
            return False
        return time.perf_counter() >= self._circuit_open_until

    def _url_key(self, short_code: str) -> str:
        """Format consistent namespaced cache key."""
        return f"url:{short_code}"

    def _clicks_key(self, short_code: str) -> str:
        """Format consistent namespaced clicks key."""
        return f"clicks:{short_code}"

    async def get_url(self, short_code: str) -> str | None:
        """Retrieve destination URL from Redis cache with fail-open error handling."""
        if not self.is_available or self.redis is None:
            self._local_misses += 1
            record_cache_operation("get", "bypass")
            return None

        key = self._url_key(short_code)
        try:
            val = await self.redis.get(key)
            if val is not None:
                self._local_hits += 1
                record_cache_operation("get", "hit")
                return str(val)
            self._local_misses += 1
            record_cache_operation("get", "miss")
            return None
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            self._circuit_open_until = time.perf_counter() + self._circuit_break_duration
            self._local_errors += 1
            record_cache_operation("get", "error")
            logger.warning(
                "Redis cache read failure for '%s': %s (fail_open=%s)",
                short_code,
                exc,
                self.fail_open,
            )
            if self.fail_open:
                return None
            raise

    async def set_url(
        self,
        short_code: str,
        original_url: str,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Store short-code to original-URL mapping in Redis with TTL."""
        if not self.is_available or self.redis is None:
            return False

        key = self._url_key(short_code)
        effective_ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl

        try:
            await self.redis.set(key, original_url, ex=effective_ttl)
            record_cache_operation("set", "ok")
            return True
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            self._circuit_open_until = time.perf_counter() + self._circuit_break_duration
            self._local_errors += 1
            record_cache_operation("set", "error")
            logger.warning(
                "Redis cache write failure for '%s': %s (fail_open=%s)",
                short_code,
                exc,
                self.fail_open,
            )
            if self.fail_open:
                return False
            raise

    async def delete_url(self, short_code: str) -> bool:
        """Invalidate cached short code mapping immediately."""
        if not self.is_available or self.redis is None:
            return False

        key = self._url_key(short_code)
        try:
            deleted_count = await self.redis.delete(key)
            record_cache_operation("delete", "ok")
            return bool(deleted_count > 0)
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            self._circuit_open_until = time.perf_counter() + self._circuit_break_duration
            self._local_errors += 1
            record_cache_operation("delete", "error")
            logger.warning(
                "Redis cache invalidation failure for '%s': %s (fail_open=%s)",
                short_code,
                exc,
                self.fail_open,
            )
            if self.fail_open:
                return False
            raise

    async def record_click(self, short_code: str) -> int | None:
        """Increment in-memory access counter in Redis."""
        if not self.is_available or self.redis is None:
            return None

        key = self._clicks_key(short_code)
        try:
            count = await self.redis.incr(key)
            return int(count)
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            self._circuit_open_until = time.perf_counter() + self._circuit_break_duration
            self._local_errors += 1
            logger.warning("Redis click count increment failed for '%s': %s", short_code, exc)
            return None

    async def get_stats(self) -> dict[str, Any]:
        """Harvest local and server-side Redis performance and hit/miss metrics."""
        total_lookups = self._local_hits + self._local_misses
        hit_ratio = round((self._local_hits / total_lookups) * 100, 2) if total_lookups > 0 else 0.0

        stats: dict[str, Any] = {
            "cache_enabled": self.enabled,
            "local_hits": self._local_hits,
            "local_misses": self._local_misses,
            "local_errors": self._local_errors,
            "local_hit_ratio_pct": hit_ratio,
        }

        if self.redis is not None:
            try:
                server_stats = await self.redis.info("stats")
                server_memory = await self.redis.info("memory")
                server_hits = int(server_stats.get("keyspace_hits", 0))
                server_misses = int(server_stats.get("keyspace_misses", 0))
                server_total = server_hits + server_misses
                server_ratio = (
                    round((server_hits / server_total) * 100, 2) if server_total > 0 else 0.0
                )

                stats["redis_server"] = {
                    "keyspace_hits": server_hits,
                    "keyspace_misses": server_misses,
                    "server_hit_ratio_pct": server_ratio,
                    "used_memory_human": server_memory.get("used_memory_human", "unknown"),
                    "connected_clients": server_stats.get("connected_clients", 0),
                    "total_commands_processed": server_stats.get("total_commands_processed", 0),
                }
            except Exception as exc:
                stats["redis_server_error"] = str(exc)

        return stats

    async def flush_all(self) -> None:
        """Flush all keys in active Redis DB (for benchmarking and clean state)."""
        if self.redis is not None:
            try:
                await self.redis.flushdb()
                self._local_hits = 0
                self._local_misses = 0
                self._local_errors = 0
            except Exception as exc:
                logger.warning("Failed to flush Redis: %s", exc)
