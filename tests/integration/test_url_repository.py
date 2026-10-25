"""Integration tests for URLRepository against real PostgreSQL database."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.url_repository import URLRepository


@pytest.mark.asyncio
async def test_create_and_retrieve_url(db_session: AsyncSession, clean_urls_table: None) -> None:
    """Verify persisting and retrieving a URL record in real PostgreSQL."""
    repo = URLRepository(db_session)
    url = await repo.create(
        original_url="https://docs.sqlalchemy.org",
        short_code="sqla-docs",
        user_id="user_123",
    )
    await db_session.commit()

    assert url.id is not None
    assert url.short_code == "sqla-docs"
    assert url.click_count == 0
    assert url.active is True

    # Retrieve by short code
    fetched = await repo.get_by_short_code("sqla-docs")
    assert fetched is not None
    assert fetched.id == url.id
    assert fetched.original_url == "https://docs.sqlalchemy.org"

    # Retrieve by ID
    fetched_by_id = await repo.get_by_id(url.id)
    assert fetched_by_id is not None
    assert fetched_by_id.short_code == "sqla-docs"


@pytest.mark.asyncio
async def test_duplicate_short_code_raises_integrity_error(
    db_session: AsyncSession, clean_urls_table: None
) -> None:
    """Verify PostgreSQL unique constraint prevents duplicate short codes."""
    repo = URLRepository(db_session)
    await repo.create(
        original_url="https://first.com",
        short_code="duplicate-code",
    )
    await db_session.commit()

    # Second insert with identical short_code must trigger IntegrityError
    with pytest.raises(IntegrityError):
        await repo.create(
            original_url="https://second.com",
            short_code="duplicate-code",
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_atomic_click_counter_increment(
    db_session: AsyncSession, clean_urls_table: None
) -> None:
    """Verify atomic database increment of click count."""
    repo = URLRepository(db_session)
    url = await repo.create(
        original_url="https://counter-test.com",
        short_code="count-test",
    )
    await db_session.commit()

    new_count = await repo.increment_click_count(url.id)
    await db_session.commit()
    assert new_count == 1

    new_count_2 = await repo.increment_click_count(url.id)
    await db_session.commit()
    assert new_count_2 == 2


@pytest.mark.asyncio
async def test_soft_delete(db_session: AsyncSession, clean_urls_table: None) -> None:
    """Verify soft deletion sets active = False."""
    repo = URLRepository(db_session)
    url = await repo.create(
        original_url="https://delete-me.com",
        short_code="del-test",
    )
    await db_session.commit()

    deleted = await repo.soft_delete(url.id)
    await db_session.commit()
    assert deleted is True

    fetched = await repo.get_by_id(url.id)
    assert fetched is not None
    assert fetched.active is False

    # Second soft delete on already inactive record returns False
    deleted_again = await repo.soft_delete(url.id)
    assert deleted_again is False
