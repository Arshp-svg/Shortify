"""Shortify API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_v1_router = APIRouter(prefix="/api/v1")

# Mount health endpoints under v1 if queried via /api/v1/health or /ready
api_v1_router.include_router(health.router)
