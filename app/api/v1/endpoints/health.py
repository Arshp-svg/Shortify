"""Health and readiness probe endpoints."""

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.url import HealthResponse, ReadyResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe", tags=["Health"])
async def health() -> HealthResponse:
    """Liveness probe returning HTTP 200 if the FastAPI application process is alive."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe", tags=["Health"])
async def ready(
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Readiness probe verifying operational connectivity to backing database."""
    checks: dict[str, str] = {}
    is_ready = True

    # 1. Check PostgreSQL connectivity
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.error("Readiness DB check failed: %s", e)
        checks["database"] = f"disconnected: {e!s}"
        is_ready = False

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    response_payload = ReadyResponse(
        status="ready" if is_ready else "unready",
        checks=checks,
    ).model_dump()

    return JSONResponse(status_code=status_code, content=response_payload)
