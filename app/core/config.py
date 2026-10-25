"""Application settings and environment configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Shortify application settings parsed from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # General
    app_name: str = "Shortify"
    environment: Literal["development", "testing", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    base_url: str = "http://localhost:8000"

    # Server Binding
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # PostgreSQL Configuration
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "shortify"
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # Connection Pool Tuning
    postgres_pool_size: int = 20
    postgres_max_overflow: int = 10
    postgres_pool_timeout: int = 30
    postgres_pool_recycle: int = 1800

    # Redis Cache & Rate Limiting
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0
    redis_timeout_seconds: float = 2.0
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    cache_fail_open: bool = True
    cache_buffer_clicks: bool = False

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_create_per_minute: int = 60
    rate_limit_burst_multiplier: float = 1.0
    rate_limit_fail_open: bool = True

    # Observability
    prometheus_metrics_enabled: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def async_database_url(self) -> str:
        """Construct or return the async PostgreSQL DSN."""
        if self.database_url_override:
            return self.database_url_override
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_server,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """Construct the Redis connection URL."""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Provide cached singleton application settings."""
    return Settings()
