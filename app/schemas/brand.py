from typing import Optional

from pydantic import BaseModel, Field


class BrandColorsRequest(BaseModel):
    """JSON body for both brand-color endpoints.

    The image may also arrive as a multipart file upload, in which case the
    route reads `file`/`max_colors` from the form and this model is unused.
    """

    image_url: Optional[str] = Field(
        default=None,
        description="Public http(s) URL or a base64 data: URI of the logo image.",
    )
    max_colors: int = Field(default=6, ge=1, le=10)


# ---- Pixel-analysis response (exact colors from real pixels) -----------------
class PixelColor(BaseModel):
    hex: str
    coverage: float = Field(..., description="Fraction of the image (0-1) this color covers.")


class PixelColorsResponse(BaseModel):
    colors: list[PixelColor]
    count: int


# ---- LLM (GPT-4o vision) response (perceived colors + semantic labels) -------
class BrandColor(BaseModel):
    hex: str
    role: str = Field(..., description="primary | secondary | accent | background | text")
    name: str = Field(..., description="Human-friendly color name, e.g. 'Navy'.")


class LlmColorsResponse(BaseModel):
    colors: list[BrandColor]
    model: str
    cost_usd: float


# ---- Hybrid response (exact pixel hexes + LLM-assigned roles/names) -----------
class HybridColor(BaseModel):
    hex: str = Field(..., description="Exact hex from pixel analysis.")
    coverage: float = Field(..., description="Fraction of the image (0-1) this color covers.")
    role: str = Field(..., description="primary | secondary | accent | background | text")
    name: str = Field(..., description="Human-friendly color name, e.g. 'Navy'.")


class HybridColorsResponse(BaseModel):
    colors: list[HybridColor]
    model: str
    cost_usd: float
