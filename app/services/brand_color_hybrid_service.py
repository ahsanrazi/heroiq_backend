"""Hybrid brand-color extraction: exact pixel hexes + gpt-4o-mini labeling.

Combines the two approaches' strengths — pixel analysis gives the exact hex
codes (and coverage), then a cheap text-only gpt-4o-mini call assigns each hex a
role + name. The LLM never sees the image and never invents hexes, so the
returned codes stay exact while still getting semantic labels.
"""

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.brand import HybridColorsResponse
from app.services.brand_color_llm_service import LABEL_MODEL, label_pixel_colors
from app.services.brand_color_pixel_service import extract_pixel_colors


async def extract_hybrid_colors(
    image_bytes: bytes,
    max_colors: int,
    tenant_id: Optional[str],
    db: AsyncSession,
) -> HybridColorsResponse:
    """Exact pixel colors with LLM-assigned roles + names."""
    pixel_colors = extract_pixel_colors(image_bytes, max_colors)
    if not pixel_colors:
        return HybridColorsResponse(colors=[], model=LABEL_MODEL, cost_usd=0.0)
    return await label_pixel_colors(pixel_colors, tenant_id, db)
