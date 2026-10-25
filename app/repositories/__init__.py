"""Repository classes export."""

from app.repositories.base import BaseRepository
from app.repositories.url_repository import URLRepository

__all__ = ["BaseRepository", "URLRepository"]
