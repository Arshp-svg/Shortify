"""Shortify main application entrypoint."""

from typing import Any

from fastapi import FastAPI

app = FastAPI(
    title="Shortify",
    description="Production-Grade URL Shortener & Backend Engineering Laboratory",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """Liveness probe returning HTTP 200 when the process is alive."""
    return {"status": "ok"}


@app.get("/", tags=["Root"])
async def root() -> dict[str, Any]:
    """Root endpoint returning service identity and documentation link."""
    return {
        "service": "Shortify",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
