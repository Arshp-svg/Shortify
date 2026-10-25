"""Generic base repository interface."""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Base repository providing database session reference."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
