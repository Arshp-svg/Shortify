"""Unit tests for Pydantic URL request and response schemas."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.schemas.url import URLCreateRequest


def test_valid_url_create_request() -> None:
    """Verify valid URL request parsing."""
    future = datetime.now(UTC) + timedelta(days=1)
    req = URLCreateRequest(
        original_url="https://docs.fastapi.tiangolo.com",
        custom_alias="my-docs",
        expires_at=future,
    )
    assert str(req.original_url) == "https://docs.fastapi.tiangolo.com/"
    assert req.custom_alias == "my-docs"
    assert req.expires_at == future


def test_invalid_scheme_rejected() -> None:
    """Verify non-HTTP schemes are rejected for SSRF defense."""
    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="javascript:alert(1)")

    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="file:///etc/passwd")


def test_reserved_alias_rejected() -> None:
    """Verify reserved route names cannot be claimed as aliases."""
    for reserved in ("health", "ready", "metrics", "docs", "static"):
        with pytest.raises(ValidationError, match="reserved route"):
            URLCreateRequest(
                original_url="https://example.com",
                custom_alias=reserved,
            )


def test_invalid_alias_format_rejected() -> None:
    """Verify custom alias pattern enforcement."""
    # Too short (< 4 chars)
    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="https://example.com", custom_alias="abc")

    # Special characters not allowed
    with pytest.raises(ValidationError):
        URLCreateRequest(original_url="https://example.com", custom_alias="bad@alias!")


def test_past_expiration_rejected() -> None:
    """Verify past expiration timestamps are rejected."""
    past = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(ValidationError, match="must be in the future"):
        URLCreateRequest(
            original_url="https://example.com",
            expires_at=past,
        )
