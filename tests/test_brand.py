import base64
import io

import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import settings
from app.services import brand_color_llm_service

TOKEN = "test-service-token"
SOLID_RGB = (26, 43, 60)       # #1A2B3C
SOLID_HEX = "#1A2B3C"


def _solid_png(color=SOLID_RGB, size=(50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _png_data_uri() -> str:
    return "data:image/png;base64," + base64.b64encode(_solid_png()).decode("ascii")


# ---- Auth gate (shared by both endpoints) ------------------------------------
@pytest.mark.anyio
async def test_pixel_requires_service_token(client: AsyncClient):
    response = await client.post("/api/brand-colors/pixel", json={})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_llm_rejects_invalid_service_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/brand-colors/llm",
        json={},
        headers={"X-Internal-Token": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


# ---- Pixel endpoint (no OpenAI, no DB) ---------------------------------------
@pytest.mark.anyio
async def test_pixel_extracts_exact_color_multipart(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/brand-colors/pixel",
        headers={"X-Internal-Token": TOKEN},
        files={"file": ("logo.png", _solid_png(), "image/png")},
        data={"max_colors": "3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert body["colors"][0]["hex"] == SOLID_HEX
    assert body["colors"][0]["coverage"] == pytest.approx(1.0, abs=0.01)


@pytest.mark.anyio
async def test_pixel_extracts_exact_color_json_data_uri(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/brand-colors/pixel",
        headers={"X-Internal-Token": TOKEN},
        json={"image_url": _png_data_uri(), "max_colors": 4},
    )
    assert response.status_code == 200
    assert response.json()["colors"][0]["hex"] == SOLID_HEX


@pytest.mark.anyio
async def test_pixel_missing_image_is_400(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/brand-colors/pixel",
        headers={"X-Internal-Token": TOKEN},
        json={},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_IMAGE"


@pytest.mark.anyio
async def test_pixel_rejects_svg(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
    response = await client.post(
        "/api/brand-colors/pixel",
        headers={"X-Internal-Token": TOKEN},
        files={"file": ("logo.svg", svg, "image/svg+xml")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_FORMAT"


# ---- LLM endpoint (OpenAI mocked, no tenant => no DB write) -------------------
class _FakeUsage:
    prompt_tokens = 120
    completion_tokens = 18


class _FakeMessage:
    content = '{"colors":[{"hex":"#1a2b3c","role":"primary","name":"Navy"}]}'


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]
    usage = _FakeUsage()


@pytest.mark.anyio
async def test_llm_extracts_and_labels_colors(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)

    async def _fake_create(image_data_uri, max_colors):
        return _FakeResponse()

    monkeypatch.setattr(brand_color_llm_service, "_create_color_extraction", _fake_create)

    response = await client.post(
        "/api/brand-colors/llm",
        headers={"X-Internal-Token": TOKEN},  # no X-Tenant-Id → no usage log / DB
        json={"image_url": _png_data_uri(), "max_colors": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-4o"
    assert body["colors"][0]["hex"] == SOLID_HEX  # normalized uppercase
    assert body["colors"][0]["role"] == "primary"
    assert body["cost_usd"] > 0


# ---- Hybrid endpoint (exact pixel hexes + gpt-4o-mini labeling, mocked) -------
class _FakeLabelResponse:
    class _Msg:
        content = '{"labels":[{"hex":"#1a2b3c","role":"primary","name":"Navy"}]}'

    choices = [type("C", (), {"message": _Msg()})()]
    usage = _FakeUsage()


class _BadLabelResponse:
    class _Msg:
        content = "not valid json"

    choices = [type("C", (), {"message": _Msg()})()]
    usage = _FakeUsage()


@pytest.mark.anyio
async def test_hybrid_keeps_exact_hex_and_labels(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)

    async def _fake_label(color_lines):
        return _FakeLabelResponse()

    monkeypatch.setattr(brand_color_llm_service, "_create_color_labeling", _fake_label)

    response = await client.post(
        "/api/brand-colors/hybrid",
        headers={"X-Internal-Token": TOKEN},  # no tenant → no DB write
        files={"file": ("logo.png", _solid_png(), "image/png")},
        data={"max_colors": "3"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-4o-mini"
    color = body["colors"][0]
    assert color["hex"] == SOLID_HEX  # EXACT pixel hex, not the lowercase LLM echo
    assert color["coverage"] == pytest.approx(1.0, abs=0.01)
    assert color["role"] == "primary"
    assert color["name"] == "Navy"
    assert body["cost_usd"] > 0


@pytest.mark.anyio
async def test_hybrid_degrades_when_labeling_fails(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)

    async def _bad_label(color_lines):
        return _BadLabelResponse()

    monkeypatch.setattr(brand_color_llm_service, "_create_color_labeling", _bad_label)

    response = await client.post(
        "/api/brand-colors/hybrid",
        headers={"X-Internal-Token": TOKEN},
        json={"image_url": _png_data_uri(), "max_colors": 3},
    )
    assert response.status_code == 200
    body = response.json()
    # Exact hexes survive even when labeling can't be parsed.
    assert body["colors"][0]["hex"] == SOLID_HEX
    assert body["colors"][0]["role"] == "primary"  # rank-0 fallback
    assert body["colors"][0]["name"] == ""
    assert body["cost_usd"] == 0
