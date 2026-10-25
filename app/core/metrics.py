"""Prometheus application metrics instrumentation and middleware."""

import logging
import re
import time

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import RequestResponseEndpoint

from app.core.config import get_settings

logger = logging.getLogger("shortify.metrics")

# 1. Traffic & Request Volume
HTTP_REQUESTS_TOTAL = Counter(
    "shortify_http_requests_total",
    "Total count of HTTP requests served by Shortify",
    ["method", "endpoint", "status"],
)

# 2. Latency Percentiles (p50, p95, p99)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "shortify_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[
        0.001,
        0.0025,
        0.005,
        0.01,
        0.025,
        0.05,
        0.1,
        0.25,
        0.5,
        1.0,
        2.5,
        5.0,
        10.0,
    ],
)

# 3. HTTP Errors
HTTP_ERRORS_TOTAL = Counter(
    "shortify_http_errors_total",
    "Total count of HTTP error responses (4xx and 5xx)",
    ["method", "endpoint", "status"],
)

# 4. In-Flight Active Requests
IN_FLIGHT_REQUESTS = Gauge(
    "shortify_in_flight_requests",
    "Number of HTTP requests currently being processed",
)

# 5. Core Domain URL Operations
URL_OPERATIONS_TOTAL = Counter(
    "shortify_url_operations_total",
    "Total count of URL domain operations executed",
    ["operation"],  # "create", "redirect", "delete", "stats"
)

# 6. Redis Cache Hit/Miss Behavior
CACHE_OPERATIONS_TOTAL = Counter(
    "shortify_cache_operations_total",
    "Total count of Redis cache operations and outcomes",
    ["operation", "result"],  # operation: "get", "set", "delete"; result: "hit", "miss", "error"
)

# 7. Database Query Latency
DB_QUERY_DURATION_SECONDS = Histogram(
    "shortify_db_query_duration_seconds",
    "Database execution duration in seconds",
    ["query_type"],
    buckets=[0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)

# 8. Rate Limiting Rejections
RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "shortify_rate_limit_rejections_total",
    "Total count of requests rejected by the rate limiter (HTTP 429)",
    ["bucket"],  # "create", "general"
)


# Route normalization patterns to avoid Prometheus cardinality explosion
RE_URL_STATS = re.compile(r"^/api/v1/urls/\d+/stats/?$")
RE_URL_DETAIL = re.compile(r"^/api/v1/urls/\d+/?$")
RE_REDIRECT = re.compile(r"^/[a-zA-Z0-9_-]{1,32}/?$")


def normalize_endpoint(path: str) -> str:
    """Normalize raw URL paths into low-cardinality endpoint patterns for Prometheus."""
    if not path or path == "/":
        return "/"
    if path in ("/health", "/ready", "/metrics"):
        return path
    if path.startswith("/docs") or path.startswith("/redoc") or path == "/openapi.json":
        return "/docs"
    if RE_URL_STATS.match(path):
        return "/api/v1/urls/{id}/stats"
    if RE_URL_DETAIL.match(path):
        return "/api/v1/urls/{id}"
    if path.startswith("/api/v1/urls"):
        return "/api/v1/urls"
    if RE_REDIRECT.match(path):
        return "/{short_code}"
    return "other"


def record_url_operation(operation: str) -> None:
    """Increment domain operation counter."""
    try:
        URL_OPERATIONS_TOTAL.labels(operation=operation).inc()
    except Exception as exc:
        logger.debug("Failed to record URL operation metric: %s", exc)


def record_cache_operation(operation: str, result: str) -> None:
    """Increment cache operation counter."""
    try:
        CACHE_OPERATIONS_TOTAL.labels(operation=operation, result=result).inc()
    except Exception as exc:
        logger.debug("Failed to record cache operation metric: %s", exc)


def record_db_query(query_type: str, duration_seconds: float) -> None:
    """Record database query execution duration."""
    try:
        DB_QUERY_DURATION_SECONDS.labels(query_type=query_type).observe(duration_seconds)
    except Exception as exc:
        logger.debug("Failed to record DB query metric: %s", exc)


def record_rate_limit_rejection(bucket: str) -> None:
    """Increment rate limit rejection counter."""
    try:
        RATE_LIMIT_REJECTIONS_TOTAL.labels(bucket=bucket).inc()
    except Exception as exc:
        logger.debug("Failed to record rate limit rejection metric: %s", exc)


async def prometheus_metrics_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Starlette middleware capturing request counts, latency histograms, and active concurrency."""
    settings = get_settings()
    if not settings.prometheus_metrics_enabled:
        return await call_next(request)

    # Exclude the metrics endpoint itself from scraping loops
    if request.url.path == "/metrics":
        return await call_next(request)

    endpoint = normalize_endpoint(request.url.path)
    method = request.method
    IN_FLIGHT_REQUESTS.inc()
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        status_code = str(response.status_code)

        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)

        if response.status_code >= 400:
            HTTP_ERRORS_TOTAL.labels(method=method, endpoint=endpoint, status=status_code).inc()

        return response
    except Exception:
        duration = time.perf_counter() - start_time
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status="500").inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)
        HTTP_ERRORS_TOTAL.labels(method=method, endpoint=endpoint, status="500").inc()
        raise
    finally:
        IN_FLIGHT_REQUESTS.dec()


def get_metrics_response() -> Response:
    """Generate Prometheus scrape response with current metrics state."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
