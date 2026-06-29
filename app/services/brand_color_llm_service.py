"""Brand-color extraction via GPT-4o vision.

The model *perceives* the logo and returns colors with semantic roles + names
(primary/accent/background...). Hex values are approximate — vision models
estimate color, they don't sample pixels — but the role/name labeling is the
part this approach is good at. For exact hexes use brand_color_pixel_service.
"""

import json
import logging
import re
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import HeroIQException, ServiceUnavailableError
from app.core.retry import OPENAI_RETRYABLE, openai_retry
from app.models.api_usage_log import ApiUsageLog
from app.models.tenant import Tenant
from app.schemas.brand import (
    BrandColor,
    HybridColor,
    HybridColorsResponse,
    LlmColorsResponse,
    PixelColor,
)
from app.services.openai_pricing import calc_cost

logger = logging.getLogger(__name__)

# Brand-color endpoints use a dedicated OpenAI key (falls back to the shared key).
client = AsyncOpenAI(api_key=settings.openai_logo_key)

VISION_MODEL = "gpt-4o"
# Cheap text-only model used by the hybrid path to label exact pixel hexes.
LABEL_MODEL = "gpt-4o-mini"

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_VALID_ROLES = {"primary", "secondary", "accent", "background", "text"}

SYSTEM_PROMPT = """You are a brand-color analyst. Examine the logo image and identify its key brand colors.

Respond ONLY with valid JSON, no markdown or explanation:
{"colors": [{"hex": "#RRGGBB", "role": "primary", "name": "Navy"}]}

Rules:
- hex: a 6-digit #RRGGBB value.
- role: one of primary, secondary, accent, background, text.
- name: a short human-friendly color name.
- Order the colors most-important first.
- Report the solid brand colors; ignore anti-aliasing and gradient noise."""


@openai_retry
async def _create_color_extraction(image_data_uri: str, max_colors: int):
    """Raw vision chat-completion call, retried on transient OpenAI errors."""
    return await client.chat.completions.create(
        model=VISION_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract up to {max_colors} brand colors from this logo."},
                    {"type": "image_url", "image_url": {"url": image_data_uri, "detail": "low"}},
                ],
            },
        ],
        temperature=0.1,
        max_tokens=400,
        timeout=20,
    )


async def extract_llm_colors(
    image_data_uri: str,
    max_colors: int,
    tenant_id: Optional[str],
    db: AsyncSession,
) -> LlmColorsResponse:
    """Run GPT-4o vision, parse + validate colors, log cost (when tenant valid)."""
    try:
        response = await _create_color_extraction(image_data_uri, max_colors)
    except OPENAI_RETRYABLE as e:
        logger.error("OpenAI brand-color extraction failed after retries: %s", e)
        raise ServiceUnavailableError("OpenAI") from e

    raw = (response.choices[0].message.content or "").strip()
    colors = _parse_colors(raw, max_colors)
    if not colors:
        logger.warning("LLM returned no usable colors. Raw: %s", raw)
        raise HeroIQException(
            code="COLOR_EXTRACTION_FAILED",
            message="Could not extract colors from the logo.",
            status_code=502,
        )

    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cost = calc_cost(VISION_MODEL, input_tokens, output_tokens)

    await _maybe_log_usage(db, tenant_id, "brand_colors_llm", VISION_MODEL, input_tokens, output_tokens, cost)

    return LlmColorsResponse(colors=colors, model=VISION_MODEL, cost_usd=cost)


def _parse_colors(raw: str, max_colors: int) -> list[BrandColor]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = parsed.get("colors", []) if isinstance(parsed, dict) else []
    colors: list[BrandColor] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        hex_val = str(item.get("hex", "")).strip().upper()
        if not _HEX_RE.match(hex_val):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role not in _VALID_ROLES:
            role = "accent"
        name = str(item.get("name", "")).strip()
        colors.append(BrandColor(hex=hex_val, role=role, name=name))
        if len(colors) >= max_colors:
            break
    return colors


async def _maybe_log_usage(
    db: AsyncSession,
    tenant_id: Optional[str],
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> None:
    """Write an ApiUsageLog row only when a real tenant is supplied.

    ApiUsageLog.tenant_id is a NOT-NULL FK, so we PK-check existence first
    (status-agnostic — PENDING onboarding tenants count). Anonymous/test calls
    with no tenant simply aren't billed.
    """
    if not tenant_id:
        return
    exists = await db.scalar(select(Tenant.id).where(Tenant.id == tenant_id))
    if not exists:
        return
    db.add(
        ApiUsageLog(
            tenant_id=tenant_id,
            operation=operation,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
    )
    await db.commit()


# ---- Hybrid labeling: assign role + name to EXACT pixel hexes (text only) -----
LABEL_SYSTEM_PROMPT = """You label brand colors. You are given the EXACT hex colors extracted from a logo and how much of the image each covers.

For each hex, return its role and a short human-friendly name. Use the hex values EXACTLY as given — never change, add, or remove a hex.

Respond ONLY with valid JSON, no markdown:
{"labels": [{"hex": "#RRGGBB", "role": "primary", "name": "Navy"}]}

role must be one of: primary, secondary, accent, background, text."""


@openai_retry
async def _create_color_labeling(color_lines: str):
    """Text-only labeling call (no image), retried on transient OpenAI errors."""
    return await client.chat.completions.create(
        model=LABEL_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": LABEL_SYSTEM_PROMPT},
            {"role": "user", "content": f"Colors:\n{color_lines}"},
        ],
        temperature=0.1,
        max_tokens=400,
        timeout=15,
    )


async def label_pixel_colors(
    pixel_colors: list[PixelColor],
    tenant_id: Optional[str],
    db: AsyncSession,
) -> HybridColorsResponse:
    """Assign role + name to each EXACT pixel hex via gpt-4o-mini (text only).

    hex + coverage always come from pixel analysis; only role/name are
    LLM-derived. On any LLM/parse failure we still return the exact pixel
    colors with fallback labels (cost 0) — the hexes are the core value.
    """
    color_lines = "\n".join(f"- {c.hex} ({round(c.coverage * 100)}%)" for c in pixel_colors)

    try:
        response = await _create_color_labeling(color_lines)
    except OPENAI_RETRYABLE as e:
        logger.warning("Color labeling unavailable; returning exact colors with fallback labels: %s", e)
        return HybridColorsResponse(colors=_fallback_hybrid(pixel_colors), model=LABEL_MODEL, cost_usd=0.0)

    raw = (response.choices[0].message.content or "").strip()
    labels = _parse_labels(raw)
    if not labels:
        logger.warning("Color labeling returned no usable labels. Raw: %s", raw)
        return HybridColorsResponse(colors=_fallback_hybrid(pixel_colors), model=LABEL_MODEL, cost_usd=0.0)

    colors = _merge_labels(pixel_colors, labels)

    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cost = calc_cost(LABEL_MODEL, input_tokens, output_tokens)
    await _maybe_log_usage(db, tenant_id, "brand_colors_hybrid", LABEL_MODEL, input_tokens, output_tokens, cost)

    return HybridColorsResponse(colors=colors, model=LABEL_MODEL, cost_usd=cost)


def _parse_labels(raw: str) -> dict[str, tuple[str, str]]:
    """Return {HEX_UPPER: (role, name)} from the LLM JSON; {} on any failure."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    items = parsed.get("labels", []) if isinstance(parsed, dict) else []
    out: dict[str, tuple[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        hex_val = str(item.get("hex", "")).strip().upper()
        if not _HEX_RE.match(hex_val):
            continue
        role = str(item.get("role", "")).strip().lower()
        if role not in _VALID_ROLES:
            role = "accent"
        out[hex_val] = (role, str(item.get("name", "")).strip())
    return out


def _merge_labels(
    pixel_colors: list[PixelColor],
    labels: dict[str, tuple[str, str]],
) -> list[HybridColor]:
    """Pair each exact pixel hex with its LLM label; fall back when unmatched."""
    merged: list[HybridColor] = []
    for rank, c in enumerate(pixel_colors):
        role, name = labels.get(c.hex, (_default_role(rank), ""))
        merged.append(HybridColor(hex=c.hex, coverage=c.coverage, role=role, name=name))
    return merged


def _fallback_hybrid(pixel_colors: list[PixelColor]) -> list[HybridColor]:
    return [
        HybridColor(hex=c.hex, coverage=c.coverage, role=_default_role(rank), name="")
        for rank, c in enumerate(pixel_colors)
    ]


def _default_role(rank: int) -> str:
    return "primary" if rank == 0 else "accent"
