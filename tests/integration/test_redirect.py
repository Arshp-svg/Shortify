"""Integration tests for high-throughput redirect endpoint GET /{short_code}."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_redirect_returns_307_and_increments_clicks(
    async_client: AsyncClient, clean_urls_table: None
) -> None:
    """Verify short code redirection returns 307 and increments click_count."""
    dest = "https://httpbin.org/get"
    create_res = await async_client.post(
        "/api/v1/urls",
        json={"original_url": dest, "custom_alias": "httpbin-redirect"},
    )
    assert create_res.status_code == 201
    url_id = create_res.json()["id"]

    # Execute redirect (follow_redirects=False to inspect 307 status)
    redirect_res = await async_client.get("/httpbin-redirect", follow_redirects=False)
    assert redirect_res.status_code == 307
    assert redirect_res.headers["Location"] == "https://httpbin.org/get"
    assert "no-cache" in redirect_res.headers.get("Cache-Control", "")

    # Verify click count incremented to 1
    stats_res = await async_client.get(f"/api/v1/urls/{url_id}/stats")
    assert stats_res.status_code == 200
    assert stats_res.json()["click_count"] == 1


@pytest.mark.asyncio
async def test_redirect_unknown_code_returns_404(
    async_client: AsyncClient, clean_urls_table: None
) -> None:
    """Verify requesting an unknown short code returns 404."""
    response = await async_client.get("/non-existent-code", follow_redirects=False)
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["code"] == "SHORT_CODE_NOT_FOUND"


@pytest.mark.asyncio
async def test_redirect_deactivated_code_returns_410(
    async_client: AsyncClient, clean_urls_table: None
) -> None:
    """Verify redirecting to a deactivated URL returns 410 Gone."""
    create_res = await async_client.post(
        "/api/v1/urls",
        json={"original_url": "https://deactivated.example.com", "custom_alias": "deact-link"},
    )
    url_id = create_res.json()["id"]

    # Delete (soft deactivation)
    await async_client.delete(f"/api/v1/urls/{url_id}")

    # Subsequent redirect must return 410 Gone
    response = await async_client.get("/deact-link", follow_redirects=False)
    assert response.status_code == 410
    data = response.json()
    assert data["error"]["code"] == "URL_EXPIRED"


@pytest.mark.asyncio
async def test_redirect_expired_url_returns_410(
    async_client: AsyncClient, db_session: AsyncSession, clean_urls_table: None
) -> None:
    """Verify expired URL returns 410 Gone when accessed."""
    # Create URL with past expiration via direct SQL insert to simulate time passage
    past_time = datetime.now(UTC) - timedelta(minutes=10)
    await db_session.execute(
        text("""
            INSERT INTO urls (short_code, original_url, expires_at, click_count, active)
            VALUES ('expired-link', 'https://expired.example.com', :past, 0, true)
        """),
        {"past": past_time},
    )
    await db_session.commit()

    response = await async_client.get("/expired-link", follow_redirects=False)
    assert response.status_code == 410
    data = response.json()
    assert data["error"]["code"] == "URL_EXPIRED"
