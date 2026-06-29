"""Shared image-input handling for the brand-color endpoints.

Both endpoints (pixel + LLM) accept the logo either as a multipart file upload
or as a JSON `image_url` (a public http(s) URL or a base64 `data:` URI). This
module normalizes all three into raw bytes, then validates them once:

  - reject SVG (neither Pillow nor OpenAI vision can read it)
  - enforce a size cap
  - confirm the bytes actually decode as a raster image

Validation failures raise HeroIQException so they surface as a clean 400 JSON
envelope via the registered exception handler.
"""

import base64
import io
import logging
from typing import Optional

import httpx
from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.core.exceptions import HeroIQException

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
FETCH_TIMEOUT_SECONDS = 10


async def resolve_image_bytes(
    image_url: Optional[str],
    upload_file: Optional[UploadFile],
) -> tuple[bytes, Optional[str]]:
    """Return (raw_bytes, declared_content_type) from whichever input was given.

    Precedence: multipart file > JSON image_url. Raises HeroIQException(400)
    when no usable image was supplied or a URL/data-URI can't be read.
    """
    if upload_file is not None:
        data = await upload_file.read()
        return data, upload_file.content_type

    if image_url:
        stripped = image_url.strip()
        if stripped.startswith("data:"):
            return _decode_data_uri(stripped)
        if stripped.startswith("http://") or stripped.startswith("https://"):
            return await _fetch_url(stripped)
        raise HeroIQException(
            code="INVALID_IMAGE_URL",
            message="image_url must be an http(s) URL or a base64 data: URI.",
            status_code=400,
        )

    raise HeroIQException(
        code="MISSING_IMAGE",
        message="Provide a logo as a multipart 'file' upload or a JSON 'image_url'.",
        status_code=400,
    )


def _decode_data_uri(uri: str) -> tuple[bytes, Optional[str]]:
    header, _, payload = uri.partition(",")
    if not payload or ";base64" not in header:
        raise HeroIQException(
            code="INVALID_IMAGE_URL",
            message="Only base64-encoded data: URIs are supported.",
            status_code=400,
        )
    mime = header[len("data:"):].split(";")[0] or None
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception as e:  # noqa: BLE001 - any decode failure is a bad input
        raise HeroIQException(
            code="INVALID_IMAGE_URL",
            message="data: URI is not valid base64.",
            status_code=400,
        ) from e
    return data, mime


async def _fetch_url(url: str) -> tuple[bytes, Optional[str]]:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS) as http:
            resp = await http.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch image_url %s: %s", url, e)
        raise HeroIQException(
            code="IMAGE_FETCH_FAILED",
            message="Could not download the image from the provided URL.",
            status_code=400,
        ) from e
    return resp.content, resp.headers.get("content-type")


def validate_and_sniff(data: bytes, content_type: Optional[str]) -> str:
    """Reject SVG/oversized/corrupt input; return the resolved image MIME type.

    The returned MIME is taken from Pillow's actual decode (not the declared
    content-type) so the LLM data: URI is always built with the true format.
    """
    if not data:
        raise HeroIQException(code="INVALID_IMAGE", message="Empty image.", status_code=400)

    if len(data) > MAX_IMAGE_BYTES:
        raise HeroIQException(
            code="IMAGE_TOO_LARGE",
            message=f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit.",
            status_code=400,
        )

    if _looks_like_svg(data, content_type):
        raise HeroIQException(
            code="UNSUPPORTED_FORMAT",
            message="SVG logos are not supported. Please upload a PNG, JPG, or WebP image.",
            status_code=400,
        )

    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format  # captured before verify() invalidates the image
            img.verify()  # cheap integrity check without full decode
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise HeroIQException(
            code="INVALID_IMAGE",
            message="The file could not be read as a PNG, JPG, or WebP image.",
            status_code=400,
        ) from e

    return Image.MIME.get(fmt, "image/png") if fmt else "image/png"


def _looks_like_svg(data: bytes, content_type: Optional[str]) -> bool:
    if content_type and "svg" in content_type.lower():
        return True
    head = data[:1024].lstrip().lower()
    return head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head


def to_data_uri(data: bytes, mime: str) -> str:
    """Build a base64 data: URI to hand to OpenAI's image_url input."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"
