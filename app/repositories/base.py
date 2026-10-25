"""Generic base repository interface."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class BaseRepository[ModelType: Base]:
    """Base repository providing database session reference."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
