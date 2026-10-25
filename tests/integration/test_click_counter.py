"""Concurrency integration tests: simultaneous redirects updating click statistics."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.repositories.url_repository import URLRepository


@pytest.mark.asyncio
async def test_concurrent_redirect_click_counter(
    test_engine: AsyncEngine, clean_urls_table: None
) -> None:
    """Verify atomic database increment of click_count under concurrent redirects.

    Acceptance criteria:
    - 50 concurrent redirect requests arrive simultaneously.
    - Each request executes atomic SQL increment on the same URL record.
    - Final click_count equals exactly 50 with 0 lost updates.
    """
    concurrency_count = 50
    short_code = "concurrent-clicks"

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # 1. Insert target URL
    async with session_factory() as session:
        repo = URLRepository(session)
        url = await repo.create(
            original_url="https://popular-link.com",
            short_code=short_code,
        )
        await session.commit()
        url_id = url.id

    # 2. Worker simulating concurrent redirect handler executing atomic counter increment
    async def simulate_redirect_click() -> int:
        async with session_factory() as session:
            repo = URLRepository(session)
            count = await repo.increment_click_count(url_id)
            await session.commit()
            return count

    # 3. Fire all 50 concurrent clicks simultaneously
    tasks = [simulate_redirect_click() for _ in range(concurrency_count)]
    results = await asyncio.gather(*tasks)

    # 4. Verify all workers completed
    assert len(results) == concurrency_count

    # 5. Verify final database state has exactly 50 clicks
    async with session_factory() as session:
        repo = URLRepository(session)
        final_record = await repo.get_by_id(url_id)
        assert final_record is not None
        assert final_record.click_count == concurrency_count
