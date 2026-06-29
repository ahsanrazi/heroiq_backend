"""Exact brand-color extraction by reading real pixels (Pillow only).

Unlike the LLM approach, this samples the actual image data, so the hex codes
are exact (no model perception/guessing). It returns the dominant colors ranked
by how much of the image they cover. It does NOT assign semantic roles or
names — that's what the LLM endpoint is for.
"""

import io
import logging

from PIL import Image

from app.schemas.brand import PixelColor

logger = logging.getLogger(__name__)

# Downscale large logos before quantizing — color proportions are preserved and
# it keeps the work fast regardless of source resolution.
_MAX_DIMENSION = 400


def extract_pixel_colors(image_bytes: bytes, max_colors: int) -> list[PixelColor]:
    """Return up to `max_colors` dominant colors as exact hex + coverage fraction."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")

    # Flatten transparency onto a white background so transparent logos don't
    # quantize the alpha edges into muddy colors.
    background = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(background, img).convert("RGB")

    img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION))

    # Quantize to a palette wider than the requested count so distinct hues are
    # captured, then pick the most frequent buckets.
    palette_size = max(max_colors * 2, 8)
    quantized = img.quantize(colors=palette_size, method=Image.Quantize.MEDIANCUT)

    palette = quantized.getpalette()  # flat [r, g, b, r, g, b, ...]
    counts = quantized.getcolors()    # list of (count, palette_index)
    if not counts or not palette:
        return []

    counts.sort(key=lambda c: c[0], reverse=True)
    total = sum(count for count, _ in counts)
    if total == 0:
        return []

    results: list[PixelColor] = []
    for count, idx in counts[:max_colors]:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        results.append(
            PixelColor(hex=f"#{r:02X}{g:02X}{b:02X}", coverage=round(count / total, 4))
        )
    return results
