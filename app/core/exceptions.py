"""Centralized exception classes and global error handlers."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx
from app.schemas.error import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class ShortifyException(Exception):
    """Base exception for all domain-specific errors."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []


class EntityNotFoundException(ShortifyException):
    """Raised when a requested resource is not found."""

    def __init__(self, message: str, code: str = "NOT_FOUND") -> None:
        super().__init__(message=message, code=code, status_code=status.HTTP_404_NOT_FOUND)


class EntityConflictException(ShortifyException):
    """Raised when a resource uniqueness constraint is violated."""

    def __init__(self, message: str, code: str = "CONFLICT") -> None:
        super().__init__(message=message, code=code, status_code=status.HTTP_409_CONFLICT)


class EntityExpiredException(ShortifyException):
    """Raised when an accessed URL has expired."""

    def __init__(self, message: str, code: str = "URL_EXPIRED") -> None:
        super().__init__(message=message, code=code, status_code=status.HTTP_410_GONE)


class ValidationException(ShortifyException):
    """Raised when business validation fails."""

    def __init__(self, message: str, code: str = "INVALID_REQUEST") -> None:
        super().__init__(message=message, code=code, status_code=status.HTTP_400_BAD_REQUEST)


class RateLimitExceededException(ShortifyException):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded. Please retry later.",
        retry_after: int = 60,
    ) -> None:
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=[{"retry_after": retry_after}],
        )
        self.retry_after = retry_after


class ServiceUnavailableException(ShortifyException):
    """Raised when downstream storage/cache is unavailable."""

    def __init__(self, message: str, code: str = "SERVICE_UNAVAILABLE") -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _build_error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    req_id = request_id_ctx.get() or "unknown"
    error_detail = ErrorDetail(
        code=code,
        message=message,
        request_id=req_id,
        details=details or [],
    )
    payload = ErrorResponse(error=error_detail).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the FastAPI application."""

    @app.exception_handler(ShortifyException)
    async def shortify_exception_handler(_: Request, exc: ShortifyException) -> JSONResponse:
        logger.warning(
            "ShortifyException [%s]: %s",
            exc.code,
            exc.message,
            extra={"status": exc.status_code},
        )
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitExceededException):
            headers["Retry-After"] = str(exc.retry_after)
        return _build_error_response(
            exc.status_code, exc.code, exc.message, exc.details, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(err.get("loc", [])), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        logger.info("RequestValidationError: %s", errors)
        return _build_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Request validation failed.",
            errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "HTTP_ERROR"
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            code = "NOT_FOUND"
        elif exc.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            code = "METHOD_NOT_ALLOWED"
        return _build_error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return _build_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_SERVER_ERROR",
            "An unexpected internal error occurred. Please contact support with the request_id.",
        )
