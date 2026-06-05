import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.deps import get_active_tenant_id
from app.config import settings
from app.main import app
from app.services import rate_limiter

TOKEN = "test-service-token"


@pytest.mark.anyio
async def test_allows_when_tokens_available(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    async def fake_consume(key, capacity, rate, ttl):
        return (1, 0)  # allowed

    monkeypatch.setattr(rate_limiter, "_consume", fake_consume)
    # Should not raise.
    await rate_limiter.check_rate_limit("tenant_1", "search")


@pytest.mark.anyio
async def test_raises_429_when_bucket_empty(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    async def fake_consume(key, capacity, rate, ttl):
        return (0, 7)  # denied, retry after 7s

    monkeypatch.setattr(rate_limiter, "_consume", fake_consume)

    with pytest.raises(HTTPException) as exc:
        await rate_limiter.check_rate_limit("tenant_1", "search")
    assert exc.value.status_code == 429
    assert exc.value.detail["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert exc.value.headers["Retry-After"] == "7"


@pytest.mark.anyio
async def test_fail_open_on_redis_error(monkeypatch):
    """A Redis outage must NOT block traffic — this is a safety net, not the
    primary gate (Next.js is). Fail open."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", True)

    async def boom(key, capacity, rate, ttl):
        raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limiter, "_consume", boom)
    # Fails open → no raise.
    await rate_limiter.check_rate_limit("tenant_1", "search")


@pytest.mark.anyio
async def test_fail_closed_returns_503(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_OPEN", False)

    async def boom(key, capacity, rate, ttl):
        raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limiter, "_consume", boom)

    with pytest.raises(HTTPException) as exc:
        await rate_limiter.check_rate_limit("tenant_1", "search")
    assert exc.value.status_code == 503
    assert exc.value.detail["error"]["code"] == "RATE_LIMITER_UNAVAILABLE"


@pytest.mark.anyio
async def test_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    async def boom(key, capacity, rate, ttl):
        raise AssertionError("_consume must not be called when disabled")

    monkeypatch.setattr(rate_limiter, "_consume", boom)
    # Disabled → no-op, no Redis call.
    await rate_limiter.check_rate_limit("tenant_1", "search")


@pytest.mark.anyio
async def test_search_endpoint_returns_429_with_retry_after(client: AsyncClient, monkeypatch):
    """End-to-end: a denied bucket surfaces as 429 + Retry-After through the
    /api/search route. Tenant resolution is overridden so no DB is needed."""
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    async def deny(key, capacity, rate, ttl):
        return (0, 3)

    monkeypatch.setattr(rate_limiter, "_consume", deny)

    async def fake_tenant():
        return "tenant_abc"

    app.dependency_overrides[get_active_tenant_id] = fake_tenant
    try:
        response = await client.post(
            "/api/search",
            json={"query": "hello there"},
            headers={"X-Internal-Token": TOKEN, "X-Tenant-Id": "tenant_abc"},
        )
    finally:
        app.dependency_overrides.pop(get_active_tenant_id, None)

    assert response.status_code == 429
    assert response.json()["detail"]["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert response.headers["retry-after"] == "3"


@pytest.mark.anyio
async def test_index_and_bulk_use_distinct_categories(monkeypatch):
    """index vs bulk resolve to different limits so a bulk flood can't drain the
    single-page budget and vice versa."""
    monkeypatch.setattr(settings, "RL_INDEX_PER_MIN", 120)
    monkeypatch.setattr(settings, "RL_INDEX_BURST", 30)
    monkeypatch.setattr(settings, "RL_BULK_PER_MIN", 20)
    monkeypatch.setattr(settings, "RL_BULK_BURST", 5)
    assert rate_limiter._limits_for("index") == (120, 30)
    assert rate_limiter._limits_for("bulk") == (20, 5)
    # Unknown category falls back to the search limits (never KeyErrors).
    assert rate_limiter._limits_for("???") == (
        settings.RL_SEARCH_PER_MIN,
        settings.RL_SEARCH_BURST,
    )
