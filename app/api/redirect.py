"""Top-level short code redirection endpoint."""

from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_url_service
from app.services.url_service import URLService

router = APIRouter(tags=["Redirection"])


@router.get(
    "/{short_code}",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Redirect short code to original destination",
    response_class=RedirectResponse,
)
async def redirect_to_original_url(
    short_code: str,
    url_service: URLService = Depends(get_url_service),
) -> RedirectResponse:
    """Resolve short code and issue HTTP 307 Temporary Redirect to target URL.

    Includes Cache-Control headers to ensure subsequent visits trigger analytics.
    """
    destination_url = await url_service.resolve_redirect(short_code)
    response = RedirectResponse(
        url=destination_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
