import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_index_requires_api_key(client: AsyncClient):
    response = await client.post(
        "/api/index",
        json={
            "wp_post_id": 1,
            "title": "Test",
            "url": "/test",
            "content": "Test content",
        },
    )
    assert response.status_code == 422 or response.status_code == 401


@pytest.mark.anyio
async def test_bulk_index_requires_pages(client: AsyncClient):
    response = await client.post(
        "/api/index/bulk",
        json={"pages": []},
        headers={"X-API-Key": "fake_key"},
    )
    assert response.status_code == 422
