import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.api_usage_log import ApiUsageLog
from app.schemas.search import SearchResult
from app.services.embedding_service import generate_embedding
from app.services.pinecone_service import query_vectors

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
