import pytest
from httpx import AsyncClient

from app.config import settings

TOKEN = "test-service-token"


@pytest.mark.anyio
async def test_search_requires_service_token(client: AsyncClient):
    # No X-Internal-Token → rejected by the service-token gate before anything else.
    response = await client.post("/api/search", json={"query": "test"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_search_rejects_invalid_service_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/search",
        json={"query": "test"},
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_search_valid_token_requires_tenant(client: AsyncClient, monkeypatch):
    # Right token passes the gate; tenant resolution then requires X-Tenant-Id.
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.post(
        "/api/search",
        json={"query": "test"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["error"]["code"] == "MISSING_TENANT"
