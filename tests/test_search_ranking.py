"""search_pages fetches SEARCH_TOP_K chunks, dedups to one result per page
(keeping the highest-scoring chunk), and returns the caller's `limit` distinct
pages sorted by score.

Mirrors the monkeypatch style in test_retry.py: stub the two external calls
(generate_embedding, query_vectors) that search_service imports by name, plus a
tiny fake DB for the usage-log write.
"""
import pytest

from app.config import settings
from app.services import search_service


class _FakeDB:
    """Minimal async DB stand-in for the ApiUsageLog write in search_pages."""

    def add(self, _obj):
        pass

    async def commit(self):
        pass


def _match(page_id: int, score: float):
    return {
        "id": f"page_{page_id}_chunk_0",
        "score": score,
        "metadata": {
            "wp_post_id": page_id,
            "display_title": f"Page {page_id}",
            "summary": f"Summary {page_id}",
            "recommended_cta": "Learn More",
            "page_url": f"https://example.com/{page_id}",
            "chunk_text": f"chunk for page {page_id}",
        },
    }


@pytest.mark.anyio
async def test_search_uses_top_k_and_dedups_by_page(monkeypatch):
    captured = {}

    async def fake_embed(query):
        return {"embedding": [0.1] * 1536, "usage_tokens": 5}

    async def fake_query(**kwargs):
        captured["top_k"] = kwargs["top_k"]
        # Page 1 appears twice (0.7 then 0.9): dedup must keep 0.9.
        return [
            _match(1, 0.70),
            _match(2, 0.85),
            _match(1, 0.90),
            _match(3, 0.80),
            _match(4, 0.60),
        ]

    monkeypatch.setattr(search_service, "generate_embedding", fake_embed)
    monkeypatch.setattr(search_service, "query_vectors", fake_query)

    results = await search_service.search_pages(
        query="dental implant cost", tenant_id="t1", limit=3, db=_FakeDB(),
    )

    # Fetched the widened top_k (not the old 5).
    assert captured["top_k"] == settings.SEARCH_TOP_K == 20
    # Deduped to distinct pages, highest score per page, top-3 by score.
    assert [r.wp_post_id for r in results] == [1, 2, 3]
    assert results[0].score == 0.90            # kept page 1's best chunk, not 0.70
    assert len(results) == 3
    assert len({r.wp_post_id for r in results}) == 3   # all distinct pages
