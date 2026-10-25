"""Core URL lifecycle business logic service."""

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    EntityConflictException,
    EntityExpiredException,
    EntityNotFoundException,
    ShortifyException,
)
from app.core.metrics import record_url_operation
from app.models.url import URL
from app.repositories.url_repository import URLRepository
from app.schemas.url import URLCreateRequest, URLResponse, URLStatsResponse
from app.services.base62 import generate_random_code
from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class URLService:
    """Service orchestrating URL creation, resolution, validation, and analytics."""

    def __init__(
        self,
        repository: URLRepository,
        base_url: str,
        cache_service: CacheService | None = None,
        buffer_clicks: bool = False,
    ) -> None:
        self.repository = repository
        self.base_url = base_url.rstrip("/")
        self.cache_service = cache_service
        self.buffer_clicks = buffer_clicks

    def _to_response(self, url: URL) -> URLResponse:
        """Convert an ORM URL record to a public URLResponse schema."""
        return URLResponse(
            id=url.id,
            short_code=url.short_code,
            short_url=f"{self.base_url}/{url.short_code}",
            original_url=url.original_url,
            created_at=url.created_at,
            expires_at=url.expires_at,
            click_count=url.click_count,
            active=url.active,
        )

    async def create_url(
        self, payload: URLCreateRequest, user_id: str | None = None
    ) -> URLResponse:
        """Create a shortened URL, resolving collisions and enforcing uniqueness constraints."""
        target_url = str(payload.original_url)

        # 1. Custom Alias Flow
        if payload.custom_alias:
            alias = payload.custom_alias.strip()
            # Optimistic check
            existing = await self.repository.get_by_short_code(alias)
            if existing:
                raise EntityConflictException(
                    f"Custom alias '{alias}' is already in use.",
                    code="ALIAS_ALREADY_EXISTS",
                )
            try:
                url_record = await self.repository.create(
                    original_url=target_url,
                    short_code=alias,
                    expires_at=payload.expires_at,
                    user_id=user_id,
                )
                record_url_operation("create")
                return self._to_response(url_record)
            except IntegrityError as exc:
                raise EntityConflictException(
                    f"Custom alias '{alias}' is already in use.",
                    code="ALIAS_ALREADY_EXISTS",
                ) from exc

        # 2. Random Base62 Generation with Collision Retry Loop
        max_retries = 3
        for attempt in range(max_retries):
            short_code = generate_random_code(7)
            try:
                url_record = await self.repository.create(
                    original_url=target_url,
                    short_code=short_code,
                    expires_at=payload.expires_at,
                    user_id=user_id,
                )
                record_url_operation("create")
                return self._to_response(url_record)
            except IntegrityError:
                logger.warning(
                    "Collision detected for generated short_code '%s' (attempt %d/%d). Retrying...",
                    short_code,
                    attempt + 1,
                    max_retries,
                )
                await self.repository.session.rollback()

        raise ShortifyException(
            "Failed to generate a unique short code after multiple attempts. Please retry.",
            code="COLLISION_RETRY_EXHAUSTED",
            status_code=500,
        )

    async def resolve_redirect(self, short_code: str) -> str:
        """Resolve short code to target URL via Cache-Aside with fallback to PostgreSQL."""
        # 1. Fast Cache Read Probe
        if self.cache_service is not None:
            cached_destination = await self.cache_service.get_url(short_code)
            if cached_destination is not None:
                # Cache Hit: record click and return immediately
                await self.cache_service.record_click(short_code)
                if not self.buffer_clicks:
                    await self.repository.increment_click_count_by_code(short_code)
                record_url_operation("redirect")
                return cached_destination

        # 2. Database Fallback (Cache Miss or Cache Unavailable)
        url_record = await self.repository.get_by_short_code(short_code)

        if url_record is None:
            raise EntityNotFoundException(
                f"Short code '{short_code}' does not exist.",
                code="SHORT_CODE_NOT_FOUND",
            )

        if not url_record.active or url_record.is_expired:
            raise EntityExpiredException(
                f"Short code '{short_code}' has expired or is deactivated.",
                code="URL_EXPIRED",
            )

        # 3. Populate Cache on Miss (Cache-Aside Pattern)
        if self.cache_service is not None:
            ttl = None
            if url_record.expires_at:
                delta = int((url_record.expires_at - datetime.now(UTC)).total_seconds())
                if delta > 0:
                    ttl = delta
            await self.cache_service.set_url(short_code, url_record.original_url, ttl_seconds=ttl)
            await self.cache_service.record_click(short_code)

        # 4. Atomic Click Count Increment in Database
        await self.repository.increment_click_count(url_record.id)
        record_url_operation("redirect")
        return url_record.original_url

    async def get_url(self, url_id: int) -> URLResponse:
        """Retrieve URL metadata by ID."""
        url_record = await self.repository.get_by_id(url_id)
        if url_record is None:
            raise EntityNotFoundException(
                f"URL with ID {url_id} not found.",
                code="URL_NOT_FOUND",
            )
        return self._to_response(url_record)

    async def get_url_stats(self, url_id: int) -> URLStatsResponse:
        """Retrieve URL analytics and expiration state."""
        url_record = await self.repository.get_by_id(url_id)
        if url_record is None:
            raise EntityNotFoundException(
                f"URL with ID {url_id} not found.",
                code="URL_NOT_FOUND",
            )
        record_url_operation("stats")
        return URLStatsResponse(
            id=url_record.id,
            short_code=url_record.short_code,
            short_url=f"{self.base_url}/{url_record.short_code}",
            original_url=url_record.original_url,
            created_at=url_record.created_at,
            expires_at=url_record.expires_at,
            click_count=url_record.click_count,
            active=url_record.active,
            is_expired=url_record.is_expired,
        )

    async def delete_url(self, url_id: int) -> None:
        """Soft-deactivate URL by ID and invalidate active cache entry."""
        url_record = await self.repository.get_by_id(url_id)
        if url_record is None:
            raise EntityNotFoundException(
                f"URL with ID {url_id} not found.",
                code="URL_NOT_FOUND",
            )
        deleted = await self.repository.soft_delete(url_id)
        if not deleted:
            raise EntityNotFoundException(
                f"URL with ID {url_id} not found or already deactivated.",
                code="URL_NOT_FOUND",
            )
        # Immediate Cache Invalidation
        if self.cache_service is not None:
            await self.cache_service.delete_url(url_record.short_code)
        record_url_operation("delete")
