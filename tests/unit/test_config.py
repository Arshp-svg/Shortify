"""Unit tests for application configuration and settings."""

from app.core.config import Settings


def test_default_settings() -> None:
    """Verify default settings instantiation."""
    settings = Settings()
    assert settings.app_name == "Shortify"
    assert settings.api_port == 8000
    assert "postgresql+asyncpg://" in settings.async_database_url
    assert "redis://" in settings.redis_url


def test_custom_database_url_override() -> None:
    """Verify that DATABASE_URL override takes precedence."""
    override = "postgresql+asyncpg://user:pass@test-host:5432/test_db"
    settings = Settings(DATABASE_URL=override)
    assert settings.async_database_url == override
