import pytest
from httpx import AsyncClient

from app.config import settings

TOKEN = "test-service-token"


@pytest.mark.anyio
async def test_index_requires_service_token(client: AsyncClient):
    response = await client.post(
        "/api/index",
        json={
            "wp_post_id": 1,
            "title": "Test",
            "url": "/test",
            "content": "Test content",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_bulk_index_requires_service_token(client: AsyncClient):
    response = await client.post("/api/index/bulk", json={"pages": []})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_index_valid_token_requires_tenant(client: AsyncClient, monkeypatch):
    # Right token passes the gate; tenant resolution then requires X-Tenant-Id.
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/index",
        json={
            "wp_post_id": 1,
            "title": "Test",
            "url": "/test",
            "content": "Test content",
        },
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "MISSING_TENANT"
