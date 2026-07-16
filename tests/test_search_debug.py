"""GET /api/search/debug returns every raw Pinecone match — no dedup, no [:limit],
no score rounding — annotated with what live search would have kept.

Monkeypatch style mirrors test_search_ranking.py (stub generate_embedding and
query_vectors by name on search_service); auth style mirrors test_search.py.
No _FakeDB here — the debug path takes no session at all, which is the point.
"""
import pytest
from httpx import AsyncClient

from app.config import settings
from app.services import search_service

TOKEN = "test-service-token"


def _match(page_id: int, chunk: int, score: float, **meta_overrides):
    meta = {
        "wp_post_id": page_id,
        "display_title": f"Page {page_id}",
        "page_title": f"Raw WP Title {page_id}",
        "summary": f"Summary {page_id}",
        "recommended_cta": "Learn More",
        "page_url": f"https://example.com/{page_id}",
        "post_type": "page",
        "chunk_index": chunk,
        "chunk_text": f"chunk {chunk} for page {page_id}",
    }
    meta.update(meta_overrides)
    return {"id": f"page_{page_id}_chunk_{chunk}", "score": score, "metadata": meta}


async def _fake_embed(query):
    return {"embedding": [0.1] * 1536, "usage_tokens": 7}


def _stub(monkeypatch, matches, capture=None):
    async def fake_query(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        return matches

    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setattr(search_service, "generate_embedding", _fake_embed)
    monkeypatch.setattr(search_service, "query_vectors", fake_query)


@pytest.mark.anyio
async def test_debug_requires_service_token(client: AsyncClient):
    response = await client.get("/api/search/debug?q=test&tenant=t1")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_debug_rejects_invalid_service_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "HEROIQ_INTERNAL_API_TOKEN", TOKEN)
    response = await client.get(
        "/api/search/debug?q=test&tenant=t1",
        headers={"X-Internal-Token": "wrong-token"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "SERVICE_UNAUTHORIZED"


@pytest.mark.anyio
async def test_debug_returns_all_matches_without_dedup(client: AsyncClient, monkeypatch):
    # Page 1 has two chunks. Live search would collapse them to one; debug must not.
    _stub(monkeypatch, [
        _match(1, 0, 0.70),
        _match(2, 0, 0.85),
        _match(1, 1, 0.90),
        _match(3, 0, 0.80),
    ])

    response = await client.get(
        "/api/search/debug?q=dental+implant+cost&tenant=t1",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["match_count"] == 4  # all four, not deduped
    assert body["distinct_pages"] == 3
    assert len(body["matches"]) == 4
    # Both chunks of page 1 survive to the response.
    assert [m["id"] for m in body["matches"] if m["wp_post_id"] == 1] == [
        "page_1_chunk_0",
        "page_1_chunk_1",
    ]
    # Pinecone's original order is preserved, not re-sorted.
    assert [m["score"] for m in body["matches"]] == [0.70, 0.85, 0.90, 0.80]
    assert body["namespace"] == "tenant_t1"
    assert body["embed_tokens"] == 7
    assert body["query"] == "dental implant cost"


@pytest.mark.anyio
async def test_debug_preserves_raw_unrounded_scores(client: AsyncClient, monkeypatch):
    # The live path does round(score, 2), collapsing these two to 0.90/0.90.
    _stub(monkeypatch, [_match(1, 0, 0.9012), _match(2, 0, 0.8974)])

    response = await client.get(
        "/api/search/debug?q=test&tenant=t1",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    assert [m["score"] for m in response.json()["matches"]] == [0.9012, 0.8974]


@pytest.mark.anyio
async def test_debug_annotates_dedup_winners_and_live_rank(client: AsyncClient, monkeypatch):
    _stub(monkeypatch, [
        _match(1, 0, 0.70),   # loses dedup to page 1 chunk 1
        _match(2, 0, 0.85),   # live rank 2
        _match(1, 1, 0.90),   # live rank 1
        _match(3, 0, 0.80),   # live rank 3
    ])

    response = await client.get(
        "/api/search/debug?q=test&tenant=t1",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    by_id = {m["id"]: m for m in response.json()["matches"]}

    # The lower-scoring chunk of page 1 is shown but marked as a dedup loser.
    assert by_id["page_1_chunk_0"]["survives_dedup"] is False
    assert by_id["page_1_chunk_0"]["live_rank"] is None

    assert by_id["page_1_chunk_1"]["survives_dedup"] is True
    assert by_id["page_1_chunk_1"]["live_rank"] == 1
    assert by_id["page_2_chunk_0"]["live_rank"] == 2
    assert by_id["page_3_chunk_0"]["live_rank"] == 3


@pytest.mark.anyio
async def test_debug_tolerates_malformed_vector(client: AsyncClient, monkeypatch):
    # Live search bracket-accesses meta["display_title"] and 500s on this vector.
    # Debug must surface it instead — that's plausibly the bug being hunted.
    broken = _match(1, 0, 0.90)
    del broken["metadata"]["display_title"]
    del broken["metadata"]["page_url"]
    _stub(monkeypatch, [broken, _match(2, 0, 0.80)])

    response = await client.get(
        "/api/search/debug?q=test&tenant=t1",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    first = response.json()["matches"][0]
    assert first["display_title"] is None
    assert first["page_url"] is None
    # Still ranked normally despite the missing keys.
    assert first["live_rank"] == 1
    assert first["chunk_text"] == "chunk 0 for page 1"


@pytest.mark.anyio
async def test_debug_defaults_to_live_top_k_and_accepts_override(client: AsyncClient, monkeypatch):
    captured = {}
    _stub(monkeypatch, [_match(1, 0, 0.9)], capture=captured)

    # Default mirrors what live search fetches.
    response = await client.get(
        "/api/search/debug?q=test&tenant=t1",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    assert captured["top_k"] == settings.SEARCH_TOP_K == 20
    assert captured["tenant_id"] == "t1"
    assert response.json()["top_k"] == 20

    # Override widens the recall probe.
    response = await client.get(
        "/api/search/debug?q=test&tenant=t1&top_k=100",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    assert captured["top_k"] == 100


@pytest.mark.anyio
async def test_debug_needs_no_tenant_header_and_rejects_top_k_over_cap(
    client: AsyncClient, monkeypatch
):
    _stub(monkeypatch, [_match(1, 0, 0.9)])

    # ?tenant= alone is enough — no X-Tenant-Id, no ACTIVE check, no DB session.
    response = await client.get(
        "/api/search/debug?q=test&tenant=inactive-tenant",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 200
    assert response.json()["tenant_id"] == "inactive-tenant"

    # top_k is capped at 100.
    response = await client.get(
        "/api/search/debug?q=test&tenant=t1&top_k=101",
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 422
