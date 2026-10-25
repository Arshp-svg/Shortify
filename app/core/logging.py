"""Structured JSON logging with correlation/request ID propagation."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable storing the current request ID
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="")


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that outputs structured JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "shortify",
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include request_id from context if available
        req_id = request_id_ctx.get()
        if req_id:
            log_payload["request_id"] = req_id

        # Merge extra attributes if provided
        for key in ("method", "path", "status", "duration_ms", "client_ip"):
            if hasattr(record, key):
                log_payload[key] = getattr(record, key)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


def setup_logging(log_level: str = "INFO") -> None:
    """Configure root logger to use JSON formatting."""
    root_logger = logging.getLogger()
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate log lines
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # Normalize noisy loggers
    for logger_name in ("uvicorn.access", "uvicorn.error", "sqlalchemy.engine"):
        log = logging.getLogger(logger_name)
        log.handlers = []
        log.propagate = True
