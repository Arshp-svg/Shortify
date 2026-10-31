"""Pydantic schemas for URL operations, analytics, and health checks."""

import ipaddress
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Reserved endpoints that cannot be used as custom aliases
RESERVED_ALIASES = {
    "health",
    "ready",
    "metrics",
    "docs",
    "redoc",
    "openapi.json",
    "api",
    "v1",
    "favicon.ico",
    "static",
}


class URLCreateRequest(BaseModel):
    """Payload for creating a new shortened URL."""

    original_url: Annotated[HttpUrl, Field(max_length=2048, description="Target destination URL")]
    custom_alias: Annotated[
        str | None,
        Field(
            default=None,
            min_length=4,
            max_length=32,
            pattern=r"^[a-zA-Z0-9_-]{4,32}$",
            description="Optional custom alias containing letters, numbers, underscores, or hyphens",
        ),
    ] = None
    expires_at: Annotated[
        datetime | None,
        Field(default=None, description="Optional future expiration timestamp in UTC"),
    ] = None

    @field_validator("original_url")
    @classmethod
    def validate_scheme(cls, v: HttpUrl) -> HttpUrl:
        """Ensure scheme is http/https and prohibit loopback, link-local, and SSRF destinations."""
        if v.scheme not in ("http", "https"):
            raise ValueError(f"URL scheme '{v.scheme}' is not allowed. Must be http or https.")

        host = v.host
        if not host:
            raise ValueError("URL host cannot be empty.")

        lower_host = host.lower()
        if lower_host in ("localhost", "0.0.0.0") or lower_host.endswith(  # nosec B104
            (".local", ".internal", ".lan")
        ):
            raise ValueError(f"Destination host '{host}' is prohibited for security (SSRF prevention).")

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError(f"Destination IP '{host}' is prohibited for security (SSRF prevention).")
            if str(ip) == "169.254.169.254":
                raise ValueError(f"Access to metadata IP '{host}' is prohibited.")
        except ValueError as err:
            if "prohibited" in str(err):
                raise

        return v

    @field_validator("custom_alias")
    @classmethod
    def validate_not_reserved(cls, v: str | None) -> str | None:
        """Ensure alias is not a reserved route."""
        if v is not None and v.lower() in RESERVED_ALIASES:
            raise ValueError(f"Custom alias '{v}' is a reserved route.")
        return v

    @field_validator("expires_at")
    @classmethod
    def validate_future_expiration(cls, v: datetime | None) -> datetime | None:
        """Ensure expiration date is strictly in the future."""
        if v is not None:
            now = datetime.now(UTC)
            # Ensure timezone awareness
            if v.tzinfo is None:
                v = v.replace(tzinfo=UTC)
            if v <= now:
                raise ValueError("Expiration timestamp must be in the future.")
        return v


class URLResponse(BaseModel):
    """Public representation of a shortened URL."""

    id: int
    short_code: str
    short_url: str
    original_url: str
    created_at: datetime
    expires_at: datetime | None = None
    click_count: int = 0
    active: bool = True

    model_config = {"from_attributes": True}


class URLStatsResponse(URLResponse):
    """Detailed analytics representation of a shortened URL."""

    is_expired: bool = False


class HealthResponse(BaseModel):
    """Response payload for liveness probe."""

    status: str = "ok"


class ReadyResponse(BaseModel):
    """Response payload for readiness probe."""

    status: str
    checks: dict[str, str]
