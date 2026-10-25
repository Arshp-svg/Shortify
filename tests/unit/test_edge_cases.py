"""Unit tests covering edge cases specified in roadmap Phase 5."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ShortifyException
from app.repositories.url_repository import URLRepository
from app.schemas.url import URLCreateRequest
from app.services.url_service import URLService


def test_very_long_url_boundary() -> None:
    """Verify maximum URL length (2048 characters allowed, 2049 rejected)."""
    base_prefix = "https://example.com/search?query="
    allowed_long_url = base_prefix + "x" * (2048 - len(base_prefix))
    assert len(allowed_long_url) == 2048

    # 2048 chars must be accepted
    req = URLCreateRequest(original_url=allowed_long_url)
    assert str(req.original_url) == allowed_long_url

    # 2049 chars must be rejected
    rejected_too_long = allowed_long_url + "z"
    with pytest.raises(ValidationError):
        URLCreateRequest(original_url=rejected_too_long)


def test_malformed_url_rejected() -> None:
    """Verify malformed and missing host URLs are rejected."""
    malformed_candidates = [
        "not-a-url",
        "httpx://invalid-scheme.com",
        "http://",
        "://missing-scheme",
        "ftp://example.com/file",
        "http://   /space-host",
    ]
    for candidate in malformed_candidates:
        with pytest.raises(ValidationError):
            URLCreateRequest(original_url=candidate)


@pytest.mark.asyncio
async def test_collision_retry_exhaustion_raises_500() -> None:
    """Verify that exhausting all collision retries raises ShortifyException."""
    mock_repo = AsyncMock(spec=URLRepository)
    mock_session = AsyncMock()
    mock_repo.session = mock_session
    mock_repo.create = AsyncMock(
        side_effect=IntegrityError("collision", params=None, orig=Exception())
    )

    service = URLService(mock_repo, base_url="http://test")
    future = datetime.now(UTC) + timedelta(days=1)
    payload = URLCreateRequest(original_url="https://example.com", expires_at=future)

    with pytest.raises(ShortifyException) as exc_info:
        await service.create_url(payload)

    assert exc_info.value.code == "COLLISION_RETRY_EXHAUSTED"
    assert exc_info.value.status_code == 500
    assert mock_repo.create.call_count == 3
