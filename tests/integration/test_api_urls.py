"""Integration tests for URL creation, retrieval, stats, and deactivation API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_short_url_generated_code(
    async_client: AsyncClient, clean_urls_table: None
) -> None:
    """Verify creating a short URL with randomly generated Base62 code."""
    payload = {
        "original_url": "https://fastapi.tiangolo.com/tutorial/",
    }
    response = await async_client.post("/api/v1/urls", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["id"] is not None
    assert len(data["short_code"]) == 7
    assert data["original_url"] == "https://fastapi.tiangolo.com/tutorial/"
    assert data["click_count"] == 0
    assert data["active"] is True
    assert data["short_url"].endswith(data["short_code"])


@pytest.mark.asyncio
async def test_create_short_url_custom_alias(
    async_client: AsyncClient, clean_urls_table: None
) -> None:
    """Verify creating a short URL with a custom alias."""
    payload = {
        "original_url": "https://docs.pydantic.dev/",
        "custom_alias": "pydantic-docs",
    }
    response = await async_client.post("/api/v1/urls", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["short_code"] == "pydantic-docs"

    # Second attempt with identical custom alias must return 409 Conflict
    response_dup = await async_client.post("/api/v1/urls", json=payload)
    assert response_dup.status_code == 409
    err = response_dup.json()
    assert err["error"]["code"] == "ALIAS_ALREADY_EXISTS"


@pytest.mark.asyncio
async def test_get_url_by_id(async_client: AsyncClient, clean_urls_table: None) -> None:
    """Verify retrieving URL metadata by ID."""
    create_res = await async_client.post(
        "/api/v1/urls", json={"original_url": "https://python.org"}
    )
    url_id = create_res.json()["id"]

    res = await async_client.get(f"/api/v1/urls/{url_id}")
    assert res.status_code == 200
    assert res.json()["id"] == url_id
    assert res.json()["original_url"] == "https://python.org/"

    # Non-existent ID returns 404
    res_404 = await async_client.get("/api/v1/urls/999999")
    assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_get_url_stats(async_client: AsyncClient, clean_urls_table: None) -> None:
    """Verify URL analytics and stats retrieval."""
    create_res = await async_client.post(
        "/api/v1/urls", json={"original_url": "https://example.com/stats-test"}
    )
    url_id = create_res.json()["id"]

    res = await async_client.get(f"/api/v1/urls/{url_id}/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == url_id
    assert data["click_count"] == 0
    assert data["is_expired"] is False


@pytest.mark.asyncio
async def test_delete_url_lifecycle(async_client: AsyncClient, clean_urls_table: None) -> None:
    """Verify soft deactivation and subsequent stats."""
    create_res = await async_client.post(
        "/api/v1/urls", json={"original_url": "https://to-be-deleted.com"}
    )
    url_id = create_res.json()["id"]

    # Delete (soft deactivation)
    del_res = await async_client.delete(f"/api/v1/urls/{url_id}")
    assert del_res.status_code == 204

    # Stats shows active = False
    stats_res = await async_client.get(f"/api/v1/urls/{url_id}/stats")
    assert stats_res.status_code == 200
    assert stats_res.json()["active"] is False

    # Second delete returns 404
    del_again = await async_client.delete(f"/api/v1/urls/{url_id}")
    assert del_again.status_code == 404
