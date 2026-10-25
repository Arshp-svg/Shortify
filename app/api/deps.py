"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.core.redis import get_redis_client
from app.repositories.url_repository import URLRepository
from app.services.cache_service import CacheService
from app.services.url_service import URLService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session dependency."""
    async for session in get_db_session():
        yield session


def get_current_settings() -> Settings:
    """Provide cached application settings dependency."""
    return get_settings()


def get_cache_service(
    settings: Settings = Depends(get_current_settings),
) -> CacheService:
    """Provide CacheService dependency injected with active Redis client and settings."""
    redis_client = get_redis_client() if settings.cache_enabled else None
    return CacheService(
        redis_client=redis_client,
        default_ttl=settings.cache_ttl_seconds,
        fail_open=settings.cache_fail_open,
        enabled=settings.cache_enabled,
    )


def get_url_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
    cache_service: CacheService = Depends(get_cache_service),
) -> URLService:
    """Provide URLService dependency injected with active session, settings, and cache."""
    repository = URLRepository(db)
    return URLService(
        repository=repository,
        base_url=settings.base_url,
        cache_service=cache_service,
        buffer_clicks=settings.cache_buffer_clicks,
    )
