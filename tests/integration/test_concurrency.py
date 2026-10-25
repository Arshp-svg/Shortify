"""Concurrency integration tests: race conditions on duplicate alias creation in PostgreSQL."""

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.repositories.url_repository import URLRepository


@pytest.mark.asyncio
async def test_concurrent_alias_creation_race_condition(
    test_engine: AsyncEngine, clean_urls_table: None
) -> None:
    """Race-condition verification:

    Spawns 20 concurrent asynchronous tasks attempting to insert the exact same
    short_code into PostgreSQL simultaneously across separate database connections.

    Acceptance criteria:
    - Exactly 1 task succeeds in committing to PostgreSQL.
    - Exactly 19 tasks fail with IntegrityError due to the unique constraint.
    - Zero data corruption or duplicate rows exist in the database.
    """
    concurrency_count = 20
    target_alias = "race-winner"
    success_count = 0
    failure_count = 0

    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async def attempt_insert(worker_id: int) -> bool:
        nonlocal success_count, failure_count
        async with session_factory() as session:
            repo = URLRepository(session)
            try:
                await repo.create(
                    original_url=f"https://worker-{worker_id}.example.com",
                    short_code=target_alias,
                )
                await session.commit()
                success_count += 1
                return True
            except IntegrityError:
                await session.rollback()
                failure_count += 1
                return False

    # Fire all 20 insert attempts simultaneously
    tasks = [attempt_insert(i) for i in range(concurrency_count)]
    results = await asyncio.gather(*tasks)

    # Validate exact race condition resolution
    assert results.count(True) == 1, "Exactly one concurrent insert must succeed"
    assert results.count(False) == concurrency_count - 1, "All other concurrent inserts must fail"
    assert success_count == 1
    assert failure_count == concurrency_count - 1

    # Verify database state has exactly 1 record for this alias
    async with session_factory() as session:
        repo = URLRepository(session)
        url = await repo.get_by_short_code(target_alias)
        assert url is not None
        assert url.short_code == target_alias
