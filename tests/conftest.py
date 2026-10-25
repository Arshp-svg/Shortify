"""Pytest fixtures and configuration for real PostgreSQL integration tests."""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app

settings = get_settings()


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Provide a dedicated async engine with NullPool for each test function."""
    engine = create_async_engine(
        settings.async_database_url,
        poolclass=NullPool,
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a real PostgreSQL async session for each test, rolling back changes."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture(scope="function")
async def clean_urls_table(db_session: AsyncSession) -> AsyncGenerator[None, None]:
    """Clean the urls table before and after the test."""
    await db_session.rollback()
    await db_session.execute(text("TRUNCATE TABLE urls RESTART IDENTITY CASCADE;"))
    await db_session.commit()
    yield
    await db_session.rollback()
    await db_session.execute(text("TRUNCATE TABLE urls RESTART IDENTITY CASCADE;"))
    await db_session.commit()


@pytest_asyncio.fixture(scope="function")
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient wired with real database session dependency override."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
