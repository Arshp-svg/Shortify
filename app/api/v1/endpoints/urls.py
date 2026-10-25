"""Short URL lifecycle management endpoints."""

from fastapi import APIRouter, Depends, status

from app.api.deps import get_url_service
from app.schemas.url import URLCreateRequest, URLResponse, URLStatsResponse
from app.services.url_service import URLService

router = APIRouter(prefix="/urls", tags=["URLs"])


@router.post(
    "",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a shortened URL",
)
async def create_short_url(
    payload: URLCreateRequest,
    url_service: URLService = Depends(get_url_service),
) -> URLResponse:
    """Create a shortened URL mapping with optional custom alias and expiration."""
    return await url_service.create_url(payload)


@router.get(
    "/{id}",
    response_model=URLResponse,
    summary="Get URL metadata by ID",
)
async def get_url(
    id: int,
    url_service: URLService = Depends(get_url_service),
) -> URLResponse:
    """Retrieve metadata for a specific shortened URL by its database ID."""
    return await url_service.get_url(id)


@router.get(
    "/{id}/stats",
    response_model=URLStatsResponse,
    summary="Get URL analytics & click statistics",
)
async def get_url_stats(
    id: int,
    url_service: URLService = Depends(get_url_service),
) -> URLStatsResponse:
    """Retrieve click counts, lifecycle state, and expiration details."""
    return await url_service.get_url_stats(id)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate / soft-delete a URL",
)
async def delete_url(
    id: int,
    url_service: URLService = Depends(get_url_service),
) -> None:
    """Soft-deactivate a URL. Future redirect lookups will return 410 Gone."""
    await url_service.delete_url(id)
