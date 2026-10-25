"""Pydantic schemas for standardized API error responses."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Detailed error object within the standard error envelope."""

    code: str = Field(..., description="Machine-readable error classification code")
    message: str = Field(..., description="Human-readable explanation of error")
    request_id: str = Field(..., description="Correlation request ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the error event",
    )
    details: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional field-level validation errors or metadata",
    )


class ErrorResponse(BaseModel):
    """Top-level standard error envelope returned on 4xx/5xx responses."""

    error: ErrorDetail
