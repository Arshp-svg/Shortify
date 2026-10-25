"""Shortify main application entrypoint."""

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.api.redirect import router as redirect_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_v1_router
from app.core.config import get_settings
from app.core.database import close_db_engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import request_id_ctx, setup_logging
from app.core.metrics import get_metrics_response, prometheus_metrics_middleware
from app.core.rate_limit import rate_limit_middleware
from app.core.redis import close_redis

logger = logging.getLogger("shortify.access")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager handling startup and graceful shutdown."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Starting Shortify application [%s mode]...", settings.environment)
    yield
    logger.info("Shutting down Shortify application...")
    await close_db_engine()
    await close_redis()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Production-Grade URL Shortener & Backend Performance Laboratory",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Register centralized exception handlers
register_exception_handlers(app)


# Request ID correlation & access logging middleware
@app.middleware("http")
async def request_correlation_and_logging_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Inject X-Request-ID header, set logging context, and emit structured access log."""
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = request_id_ctx.set(req_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Log structured access event
        logger.info(
            "HTTP %s %s completed with status %d in %.2fms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        request_id_ctx.reset(token)


# Rate limiting and metrics middlewares (metrics wraps rate limiter)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(prometheus_metrics_middleware)

# Mount root health/readiness endpoints for orchestrators
app.include_router(health_router)

# Mount versioned API routes
app.include_router(api_v1_router)

@app.get("/metrics", tags=["Observability"], include_in_schema=False)
async def metrics() -> Response:
    """Prometheus metrics scrape endpoint."""
    return get_metrics_response()


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root metadata endpoint."""
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "ready": "/ready",
        "metrics": "/metrics",
    }


# Mount root redirect handler (MUST be mounted last to avoid capturing static root routes)
app.include_router(redirect_router)
