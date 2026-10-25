"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session dependency."""
    async for session in get_db_session():
        yield session


def get_current_settings() -> Settings:
    """Provide cached application settings dependency."""
    return get_settings()
