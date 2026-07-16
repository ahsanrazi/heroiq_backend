import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.api_usage_log import ApiUsageLog
from app.schemas.search import DebugMatch, SearchResult
from app.services.embedding_service import generate_embedding
from app.services.openai_pricing import calc_cost
from app.services.pinecone_service import get_namespace, query_vectors

logger = logging.getLogger(__name__)


async def search_pages(
    query: str,
    tenant_id: str,
    limit: int,
    db: AsyncSession,
) -> list[SearchResult]:
    """Core search flow: embed query → Pinecone search → deduplicate by page_id → return top results.
    No LLM call — returns pre-built search cards from Pinecone metadata.
    """
    # 1. Generate query embedding (~50ms)
    embed_result = await generate_embedding(query)
    query_embedding = embed_result["embedding"]

    # Log embedding usage
    db.add(ApiUsageLog(
        tenant_id=tenant_id,
        operation="search_embed",
        model="text-embedding-3-small",
        input_tokens=embed_result["usage_tokens"],
        output_tokens=0,
        cost_usd=calc_cost("text-embedding-3-small", embed_result["usage_tokens"]),
    ))
    await db.commit()

    # 2. Pinecone vector search (~100-200ms)
    matches = await query_vectors(
        tenant_id=tenant_id,
        query_embedding=query_embedding,
        top_k=settings.SEARCH_TOP_K,
    )

    # 3. Deduplicate by wp_post_id — keep highest scoring chunk per page
    seen_pages: dict[int, dict] = {}
    for match in matches:
        meta = match["metadata"]
        wp_post_id = meta["wp_post_id"]

        if wp_post_id not in seen_pages or match["score"] > seen_pages[wp_post_id]["score"]:
            seen_pages[wp_post_id] = {
                "wp_post_id": wp_post_id,
                "display_title": meta["display_title"],
                "summary": meta["summary"],
                "recommended_cta": meta["recommended_cta"],
                "page_url": meta["page_url"],
                "score": round(match["score"], 2),
                "matched_chunk": meta.get("chunk_text", ""),
            }

    # 4. Sort by score descending, limit results
    sorted_results = sorted(seen_pages.values(), key=lambda x: x["score"], reverse=True)[:limit]

    return [SearchResult(**r) for r in sorted_results]


async def debug_search_pages(
    query: str,
    tenant_id: str,
    top_k: int,
) -> dict:
    """Raw search trace: embed → Pinecone → annotate. Nothing is dropped.

    Deliberately mirrors search_pages steps 1-2 and then STOPS: it applies
    neither the dedup-by-wp_post_id nor the [:limit] slice, and does not round
    the score. Those two reductions plus the rounding are the *entire* funnel
    between Pinecone and what the widget renders (there is no score threshold
    anywhere), so bypassing them is the whole point of this endpoint.

    If the embedding model or the query params change in search_pages, they must
    change here too — otherwise this stops reflecting live behaviour and the
    live_rank annotation starts lying.

    Takes no AsyncSession on purpose: unlike search_pages this writes no
    ApiUsageLog row. That keeps debug traffic out of tenant billing, and avoids
    a 500 when tenant_id names a tenant that doesn't exist (ApiUsageLog.tenant_id
    is a NOT-NULL FK). The trade-off is a real but untracked OpenAI embed call
    per request (~$0.00002/1K tokens).
    """
    # 1. Same embedding call as search_pages — minus the usage log.
    embed_result = await generate_embedding(query)
    query_embedding = embed_result["embedding"]

    # 2. Same Pinecone query as search_pages, but with the caller's top_k so a
    #    recall probe can ask "is it outside the top 20, or just ranked 14th?"
    matches = await query_vectors(
        tenant_id=tenant_id,
        query_embedding=query_embedding,
        top_k=top_k,
    )

    # 3. Replay the live funnel read-only: work out which chunk would win dedup
    #    for its page (mirrors search_pages step 3) and where that page would
    #    land (mirrors step 4), but annotate rather than reduce.
    #    Matches are tracked by position in `matches`, not by vector id — a
    #    malformed namespace could repeat an id, and position is unambiguous.
    best_pos_by_page: dict[int, int] = {}
    for pos, match in enumerate(matches):
        wp_post_id = (match.get("metadata") or {}).get("wp_post_id")
        if wp_post_id is None:
            continue  # can't attribute to a page; shown, but never a dedup winner
        best_pos = best_pos_by_page.get(wp_post_id)
        if best_pos is None or match["score"] > matches[best_pos]["score"]:
            best_pos_by_page[wp_post_id] = pos

    # live_rank ranks ALL dedup winners; the caller applies their own cutoff.
    # The live limit is caller-supplied (SearchRequest.limit, default 3) so this
    # can't know it — ranks 1-3 are what the widget ships today.
    winning_positions = sorted(
        best_pos_by_page.values(), key=lambda p: matches[p]["score"], reverse=True
    )
    rank_by_pos = {pos: i + 1 for i, pos in enumerate(winning_positions)}

    debug_matches = []
    for pos, match in enumerate(matches):
        meta = match.get("metadata") or {}
        debug_matches.append(DebugMatch(
            id=match["id"],
            score=match["score"],  # raw — never rounded
            live_rank=rank_by_pos.get(pos),
            survives_dedup=pos in rank_by_pos,
            wp_post_id=meta.get("wp_post_id"),
            display_title=meta.get("display_title"),
            page_title=meta.get("page_title"),
            chunk_index=meta.get("chunk_index"),
            chunk_text=meta.get("chunk_text"),
            page_url=meta.get("page_url"),
            post_type=meta.get("post_type"),
        ))

    return {
        "namespace": get_namespace(tenant_id),
        "match_count": len(debug_matches),
        "distinct_pages": len(best_pos_by_page),
        "embed_tokens": embed_result["usage_tokens"],
        "matches": debug_matches,
    }
