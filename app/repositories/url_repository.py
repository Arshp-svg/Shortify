"""URL repository implementation for PostgreSQL persistence."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.url import URL
from app.repositories.base import BaseRepository


class URLRepository(BaseRepository[URL]):
    """Repository handling all database operations for URL entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def create(
        self,
        original_url: str,
        short_code: str,
        expires_at: datetime | None = None,
        user_id: str | None = None,
    ) -> URL:
        """Persist a new URL record into PostgreSQL."""
        url_record = URL(
            original_url=original_url,
            short_code=short_code,
            expires_at=expires_at,
            user_id=user_id,
            click_count=0,
            active=True,
        )
        self.session.add(url_record)
        await self.session.flush()
        await self.session.refresh(url_record)
        return url_record

    async def get_by_id(self, url_id: int) -> URL | None:
        """Lookup URL record by primary ID."""
        stmt = select(URL).where(URL.id == url_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_short_code(self, short_code: str) -> URL | None:
        """Lookup URL record by short code."""
        stmt = select(URL).where(URL.short_code == short_code)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def increment_click_count(self, url_id: int) -> int:
        """Atomic in-database increment of click_count.

        Uses UPDATE urls SET click_count = click_count + 1 WHERE id = :id
        to eliminate lost updates under high concurrency.
        """
        stmt = (
            update(URL)
            .where(URL.id == url_id)
            .values(click_count=URL.click_count + 1)
            .returning(URL.click_count)
        )
        result = await self.session.execute(stmt)
        updated_count = result.scalar_one_or_none()
        return updated_count if updated_count is not None else 0

    async def increment_click_count_by_code(self, short_code: str) -> int:
        """Atomic in-database increment of click_count by short code."""
        stmt = (
            update(URL)
            .where(URL.short_code == short_code)
            .values(click_count=URL.click_count + 1)
            .returning(URL.click_count)
        )
        result = await self.session.execute(stmt)
        updated_count = result.scalar_one_or_none()
        return updated_count if updated_count is not None else 0

    async def soft_delete(self, url_id: int) -> bool:
        """Soft-deactivate a URL record by setting active = False."""
        stmt = (
            update(URL)
            .where(URL.id == url_id, URL.active.is_(True))
            .values(active=False)
            .returning(URL.id)
        )
        result = await self.session.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        return deleted_id is not None

    async def list_active(self, limit: int = 100, offset: int = 0) -> Sequence[URL]:
        """Retrieve paginated list of active URL records."""
        stmt = (
            select(URL)
            .where(URL.active.is_(True))
            .order_by(URL.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
