"""Shortify API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1.endpoints import health, urls

api_v1_router = APIRouter(prefix="/api/v1")

# Mount health & readiness probes
api_v1_router.include_router(health.router)

# Mount URL lifecycle management endpoints
api_v1_router.include_router(urls.router)
