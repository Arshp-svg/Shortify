"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.repositories.url_repository import URLRepository
from app.services.url_service import URLService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session dependency."""
    async for session in get_db_session():
        yield session


def get_current_settings() -> Settings:
    """Provide cached application settings dependency."""
    return get_settings()


def get_url_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_current_settings),
) -> URLService:
    """Provide URLService dependency injected with active session and settings."""
    repository = URLRepository(db)
    return URLService(repository=repository, base_url=settings.base_url)
