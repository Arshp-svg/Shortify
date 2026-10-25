"""Redis-backed sliding-window rate limiting middleware, service, and utilities."""

import logging
import time
import uuid
from dataclasses import dataclass

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import RequestResponseEndpoint

from app.core.config import Settings, get_settings
from app.core.logging import request_id_ctx
from app.core.redis import get_redis_client
from app.schemas.error import ErrorDetail, ErrorResponse

logger = logging.getLogger("shortify.ratelimit")

# Redis Lua script for atomic sliding-window rate limit evaluation.
# KEYS[1] = ratelimit:{client_ip}:{bucket}
# ARGV[1] = current_timestamp (float as string)
# ARGV[2] = window_seconds (integer as string)
# ARGV[3] = max_requests (integer as string)
# ARGV[4] = unique_member_id (string: timestamp:nonce)
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local clear_before = now - window

-- 1. Evict request timestamps outside the active sliding window
redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)

-- 2. Count requests currently recorded within the window
local current_count = redis.call('ZCARD', key)

if current_count < limit then
    -- Request is within quota: record timestamp and update TTL
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 5)
    local remaining = limit - current_count - 1
    return {1, remaining, 0}
else
    -- Request exceeds quota: find oldest entry in window to calculate retry_after
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = 1
    if oldest and #oldest >= 2 then
        local oldest_time = tonumber(oldest[2])
        local reset_time = oldest_time + window
        retry_after = math.max(1, math.ceil(reset_time - now))
    end
    return {0, 0, retry_after}
end
"""

EXEMPT_PATHS: set[str] = {
    "/",
    "/health",
    "/ready",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}


@dataclass
class RateLimitResult:
    """Outcome of a rate limit check against Redis."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    fail_open: bool = False


class RateLimiter:
    """Redis-backed sliding-window rate limiter."""

    def __init__(self, redis_client: Redis | None = None) -> None:
        self._redis = redis_client

    @property
    def redis(self) -> Redis:
        """Lazily retrieve the active Redis client."""
        if self._redis is not None:
            return self._redis
        return get_redis_client()

    async def check_rate_limit(
        self,
        client_ip: str,
        bucket: str = "default",
        limit: int = 120,
        window: int = 60,
    ) -> RateLimitResult:
        """Atomically evaluate if client_ip has exceeded limit within the sliding window."""
        key = f"ratelimit:{client_ip}:{bucket}"
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:8]}"

        try:
            raw_res = await self.redis.eval(
                SLIDING_WINDOW_LUA,
                1,
                key,
                str(now),
                str(window),
                str(limit),
                member,
            )
            # raw_res returns [allowed_flag, remaining_count, retry_after_seconds]
            allowed = bool(raw_res[0] == 1)
            remaining = int(raw_res[1])
            retry_after = int(raw_res[2])
            return RateLimitResult(
                allowed=allowed,
                limit=limit,
                remaining=remaining,
                retry_after=retry_after,
                fail_open=False,
            )
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            settings = get_settings()
            if settings.rate_limit_fail_open:
                logger.warning(
                    "Redis rate limit check failed (%s); failing open for IP %s",
                    exc,
                    client_ip,
                )
                return RateLimitResult(
                    allowed=True,
                    limit=limit,
                    remaining=limit,
                    retry_after=0,
                    fail_open=True,
                )
            logger.error("Redis rate limit check failed (%s); fail-open disabled", exc)
            raise

    async def reset(self, client_ip: str, bucket: str = "default") -> None:
        """Clear rate limit counter for a client (useful in test teardown)."""
        key = f"ratelimit:{client_ip}:{bucket}"
        try:
            await self.redis.delete(key)
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Failed to reset rate limit key %s: %s", key, exc)

    async def get_usage(self, client_ip: str, bucket: str = "default", window: int = 60) -> int:
        """Return the current number of requests recorded within the active window."""
        key = f"ratelimit:{client_ip}:{bucket}"
        now = time.time()
        clear_before = now - window
        try:
            await self.redis.zremrangebyscore(key, "-inf", clear_before)
            count = await self.redis.zcard(key)
            return int(count)
        except (RedisError, ConnectionError, TimeoutError, OSError) as exc:
            logger.warning("Failed to inspect rate limit usage for %s: %s", key, exc)
            return 0


_limiter_instance: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Retrieve or initialize the global RateLimiter singleton."""
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = RateLimiter()
    return _limiter_instance


def extract_client_ip(request: Request) -> str:
    """Extract client IP from X-Forwarded-For header or request.client socket."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


def is_path_exempt(path: str) -> bool:
    """Check if the given URL path is exempt from rate limiting."""
    if path in EXEMPT_PATHS:
        return True
    return any(path.startswith(exempt) for exempt in ("/docs", "/redoc"))


def get_rate_limit_policy(request: Request, settings: Settings) -> tuple[str, int, int]:
    """Determine bucket name, request limit, and window duration for an incoming request."""
    # Write path: URL creation is more resource-intensive
    if request.method == "POST" and request.url.path.startswith("/api/v1/urls"):
        bucket = "create"
        limit = int(settings.rate_limit_create_per_minute * settings.rate_limit_burst_multiplier)
    else:
        bucket = "general"
        limit = int(settings.rate_limit_requests_per_minute * settings.rate_limit_burst_multiplier)

    window = settings.rate_limit_window_seconds
    return bucket, limit, window


async def rate_limit_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """FastAPI/Starlette middleware enforcing Redis-backed sliding-window rate limits."""
    settings = get_settings()

    # Pass through if rate limiting is globally disabled or route is exempt
    if not settings.rate_limit_enabled or is_path_exempt(request.url.path):
        return await call_next(request)

    client_ip = extract_client_ip(request)
    bucket, limit, window = get_rate_limit_policy(request, settings)
    limiter = get_rate_limiter()

    result = await limiter.check_rate_limit(
        client_ip=client_ip,
        bucket=bucket,
        limit=limit,
        window=window,
    )

    if not result.allowed:
        req_id = request.headers.get("X-Request-ID") or request_id_ctx.get() or str(uuid.uuid4())
        logger.warning(
            "Rate limit exceeded for IP %s on %s %s [bucket: %s, limit: %d/%ds, retry_after: %ds]",
            client_ip,
            request.method,
            request.url.path,
            bucket,
            limit,
            window,
            result.retry_after,
        )
        error_detail = ErrorDetail(
            code="RATE_LIMIT_EXCEEDED",
            message=f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
            request_id=req_id,
            details=[
                {
                    "retry_after": result.retry_after,
                    "limit": result.limit,
                    "window_seconds": window,
                }
            ],
        )
        payload = ErrorResponse(error=error_detail).model_dump(mode="json")
        headers = {
            "Retry-After": str(result.retry_after),
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(result.retry_after),
            "X-Request-ID": req_id,
        }
        return JSONResponse(status_code=429, content=payload, headers=headers)

    # Allowed: proceed with request
    response = await call_next(request)

    # Attach rate limit metadata headers
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.retry_after)
    if result.fail_open:
        response.headers["X-RateLimit-FailOpen"] = "true"

    return response
