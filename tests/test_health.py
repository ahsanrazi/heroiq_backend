import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_endpoint_returns_200(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "unhealthy")
    assert "version" in data
    assert "services" in data
