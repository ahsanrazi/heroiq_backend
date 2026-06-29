"""Brand-color extraction endpoints.

Two independent approaches over the same input handling:
  - POST /api/brand-colors/pixel : exact colors from real pixels (Pillow)
  - POST /api/brand-colors/llm   : perceived colors + roles/names (GPT-4o vision)

Both accept the logo as either a multipart file upload (`file`) or a JSON
`image_url` (http(s) URL or base64 data: URI). Caller auth (service token) is
enforced at the router level; no ACTIVE-tenant requirement so onboarding works.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.brand import HybridColorsResponse, LlmColorsResponse, PixelColorsResponse
from app.services.brand_color_hybrid_service import extract_hybrid_colors
from app.services.brand_color_llm_service import extract_llm_colors
from app.services.brand_color_pixel_service import extract_pixel_colors
from app.services.image_input import resolve_image_bytes, to_data_uri, validate_and_sniff

router = APIRouter()


@router.post("/brand-colors/pixel", response_model=PixelColorsResponse)
async def brand_colors_pixel(request: Request):
    """Exact dominant colors (hex + coverage) read straight from the pixels."""
    image_url, upload, max_colors = await _parse_inputs(request)
    data, content_type = await resolve_image_bytes(image_url, upload)
    validate_and_sniff(data, content_type)
    colors = extract_pixel_colors(data, max_colors)
    return PixelColorsResponse(colors=colors, count=len(colors))


@router.post("/brand-colors/llm", response_model=LlmColorsResponse)
async def brand_colors_llm(
    request: Request,
    x_tenant_id: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
):
    """GPT-4o vision colors with semantic roles + names. Logs cost per tenant."""
    image_url, upload, max_colors = await _parse_inputs(request)
    data, content_type = await resolve_image_bytes(image_url, upload)
    mime = validate_and_sniff(data, content_type)
    data_uri = to_data_uri(data, mime)
    return await extract_llm_colors(data_uri, max_colors, x_tenant_id, db)


@router.post("/brand-colors/hybrid", response_model=HybridColorsResponse)
async def brand_colors_hybrid(
    request: Request,
    x_tenant_id: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
):
    """Exact pixel hexes labeled (role + name) by gpt-4o-mini. Logs cost per tenant."""
    image_url, upload, max_colors = await _parse_inputs(request)
    data, content_type = await resolve_image_bytes(image_url, upload)
    validate_and_sniff(data, content_type)
    return await extract_hybrid_colors(data, max_colors, x_tenant_id, db)


async def _parse_inputs(request: Request) -> tuple[Optional[str], Optional[UploadFile], int]:
    """Pull (image_url, upload_file, max_colors) from JSON or multipart, by content-type."""
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is not None and not hasattr(upload, "read"):
            upload = None  # field present but not a file
        image_url = form.get("image_url")
        image_url = image_url.strip() if isinstance(image_url, str) and image_url.strip() else None
        return image_url, upload, _coerce_max_colors(form.get("max_colors"))

    # Default: JSON body (tolerate an empty/malformed body).
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - any parse failure → treat as no body
        body = {}
    if not isinstance(body, dict):
        body = {}
    return body.get("image_url"), None, _coerce_max_colors(body.get("max_colors"))


def _coerce_max_colors(value) -> int:
    """Default 6, clamped to the 1-10 range (mirrors the Pydantic Field bounds)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 6
    return max(1, min(10, n))
