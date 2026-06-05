"""Retry + graceful-failure behavior for external OpenAI / Pinecone calls.

Mirrors the mocking style in test_search.py / test_rate_limit.py: monkeypatch the
service-level client and override FastAPI dependencies so no real network or DB
is needed. Retry waits are zeroed (tenacity wait_none) so tests don't sleep.
"""

from types import SimpleNamespace

import httpx
import pytest
import tenacity
from httpx import AsyncClient
from openai import APITimeoutError, BadRequestError

from app.api.deps import get_active_tenant_id, get_db
from app.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.main import app
from app.services import embedding_service, pinecone_service, search_service

TOKEN = "test-service-token"


def _timeout_error() -> APITimeoutError:
    """A transient OpenAI error (in OPENAI_RETRYABLE)."""
    return APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/embeddings"))


def _bad_request_error() -> BadRequestError:
    """A permanent OpenAI error (NOT retryable)."""
    req = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    resp = httpx.Response(400, request=req)
    return BadRequestError("bad input", response=resp, body=None)


def _fake_embedding_response():
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1] * 1536)],
        usage=SimpleNamespace(total_tokens=5),
    )


@pytest.fixture(autouse=True)
def _no_sleep():
    """Zero out retry backoff so tests run instantly. The decorators bake the
    wait at import time, so we mutate the live controller's wait strategy."""
    embedding_service._create_embedding.retry.wait = tenacity.wait_none()
    pinecone_service._run_sync_retry.retry.wait = tenacity.wait_none()
    yield


# ---- OpenAI embedding --------------------------------------------------------

@pytest.mark.anyio
async def test_embedding_retries_then_succeeds(monkeypatch):
    """Two transient failures, then success on the 3rd attempt → returns result."""
    calls = {"n": 0}

    async def flaky_create(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _timeout_error()
        return _fake_embedding_response()

    monkeypatch.setattr(embedding_service.client.embeddings, "create", flaky_create)

    result = await embedding_service.generate_embedding("hello")
    assert calls["n"] == 3  # 2 failures + 1 success
    assert result["usage_tokens"] == 5
    assert len(result["embedding"]) == 1536


@pytest.mark.anyio
async def test_embedding_exhausts_retries_raises_503(monkeypatch):
    """Always failing transient error → ServiceUnavailableError after N attempts."""
    calls = {"n": 0}

    async def always_timeout(*args, **kwargs):
        calls["n"] += 1
        raise _timeout_error()

    monkeypatch.setattr(embedding_service.client.embeddings, "create", always_timeout)

    with pytest.raises(ServiceUnavailableError) as exc:
        await embedding_service.generate_embedding("hello")
    assert exc.value.status_code == 503
    assert exc.value.code == "SERVICE_UNAVAILABLE"
    assert calls["n"] == settings.EXTERNAL_RETRY_ATTEMPTS


@pytest.mark.anyio
async def test_embedding_permanent_error_not_retried(monkeypatch):
    """A non-transient error (400) is raised immediately, not retried, not masked."""
    calls = {"n": 0}

    async def bad_request(*args, **kwargs):
        calls["n"] += 1
        raise _bad_request_error()

    monkeypatch.setattr(embedding_service.client.embeddings, "create", bad_request)

    with pytest.raises(BadRequestError):
        await embedding_service.generate_embedding("hello")
    assert calls["n"] == 1  # called once, no retries


# ---- Pinecone ----------------------------------------------------------------

@pytest.mark.anyio
async def test_pinecone_query_exhausts_retries_raises_503(monkeypatch):
    """Transient Pinecone failure on every attempt → 503 (Search index)."""
    calls = {"n": 0}

    class FakeIndex:
        def query(self, *args, **kwargs):
            calls["n"] += 1
            raise ConnectionError("pinecone unreachable")  # in PINECONE_RETRYABLE

    monkeypatch.setattr(pinecone_service, "_get_index", lambda: FakeIndex())

    with pytest.raises(ServiceUnavailableError) as exc:
        await pinecone_service.query_vectors("tenant_1", [0.1] * 1536, top_k=5)
    assert exc.value.status_code == 503
    assert calls["n"] == settings.EXTERNAL_RETRY_ATTEMPTS


@pytest.mark.anyio
async def test_pinecone_query_retries_then_succeeds(monkeypatch):
    """One transient failure, then a clean result on retry."""
    calls = {"n": 0}

    class FakeMatch:
        def __init__(self):
            self.id = "page_1_chunk_0"
            self.score = 0.9
            self.metadata = {"wp_post_id": 1}

    class FakeResult:
        matches = [FakeMatch()]

    class FakeIndex:
        def query(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 2:
                raise ConnectionError("blip")
            return FakeResult()

    monkeypatch.setattr(pinecone_service, "_get_index", lambda: FakeIndex())

    results = await pinecone_service.query_vectors("tenant_1", [0.1] * 1536, top_k=5)
    assert calls["n"] == 2
    assert results[0]["id"] == "page_1_chunk_0"


# ---- End-to-end: 503 surfaces through the /api/search route ------------------

@pytest.mark.anyio
async def test_search_route_returns_503_when_openai_unavailable(client: AsyncClient, monkeypatch):
    """A ServiceUnavailableError from the embedding layer surfaces as HTTP 503
    (not 500) with the consistent {"error": {...}} envelope."""
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    async def boom(query):
        raise ServiceUnavailableError("OpenAI")

    monkeypatch.setattr(search_service, "generate_embedding", boom)

    async def fake_tenant():
        return "tenant_abc"

    async def fake_db():
        yield None  # never used — embedding raises before any DB access

    app.dependency_overrides[get_active_tenant_id] = fake_tenant
    app.dependency_overrides[get_db] = fake_db
    try:
        response = await client.post(
            "/api/search",
            json={"query": "hello there"},
            headers={"X-Internal-Token": TOKEN, "X-Tenant-Id": "tenant_abc"},
        )
    finally:
        app.dependency_overrides.pop(get_active_tenant_id, None)
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
