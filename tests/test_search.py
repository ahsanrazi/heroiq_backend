import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_search_requires_api_key(client: AsyncClient):
    response = await client.post("/api/search", json={"query": "test"})
    assert response.status_code == 422 or response.status_code == 401


@pytest.mark.anyio
async def test_search_rejects_empty_query(client: AsyncClient):
    response = await client.post(
        "/api/search",
        json={"query": ""},
        headers={"X-API-Key": "fake_key"},
    )
    assert response.status_code == 422
