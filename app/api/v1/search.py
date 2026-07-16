import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, rate_limited
from app.config import settings
from app.schemas.search import DebugSearchResponse, SearchRequest, SearchResponse
from app.services.search_service import debug_search_pages, search_pages

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def ai_search(
    body: SearchRequest,
    tenant_id: str = Depends(rate_limited("search")),
    db: AsyncSession = Depends(get_db),
):
    """AI search — embed query, search Pinecone, return pre-built search cards. No LLM call."""
    start = time.time()

    results = await search_pages(
        query=body.query,
        tenant_id=tenant_id,
        limit=body.limit,
        db=db,
    )

    elapsed_ms = int((time.time() - start) * 1000)

    return SearchResponse(
        results=results,
        query=body.query,
        results_count=len(results),
        response_time_ms=elapsed_ms,
    )


@router.get("/search/debug", response_model=DebugSearchResponse)
async def ai_search_debug(
    q: str = Query(..., min_length=1, max_length=500, description="The search query to trace."),
    tenant: str = Query(..., min_length=1, description="Tenant id. Need not be ACTIVE."),
    top_k: int = Query(
        default=settings.SEARCH_TOP_K,
        ge=1,
        le=100,
        description="Chunks to fetch from Pinecone. Defaults to what live search uses.",
    ),
):
    """Internal search trace — every raw Pinecone match, no dedup, no truncation.

    Runs the same embed + query as POST /api/search then stops, so you can see
    why a page ranked where it did. Scores are raw (live search rounds to 2dp,
    which collapses near-ties), and `live_rank` / `survives_dedup` show what the
    real endpoint would have kept.

    Reading the output: `chunk_text` is NOT what was embedded — indexing embeds
    "{page_title}\\n\\n{chunk}" but stores the bare chunk as metadata, so a chunk
    can rank high on title keywords alone while its text looks irrelevant. Check
    `page_title` and `chunk_index` before concluding a match is nonsense.

    Auth: the service token, inherited from the router-level require_service_token
    gate. Tenant comes in as a query param and is deliberately NOT required to be
    ACTIVE — a paused or pending tenant is often exactly the one worth inspecting
    (same reasoning as DELETE /api/index/tenant/{tenant_id}). That also means no
    rate limit and no ApiUsageLog row: debug traffic stays out of tenant billing.
    """
    start = time.time()

    trace = await debug_search_pages(query=q, tenant_id=tenant, top_k=top_k)

    elapsed_ms = int((time.time() - start) * 1000)

    return DebugSearchResponse(
        query=q,
        tenant_id=tenant,
        top_k=top_k,
        response_time_ms=elapsed_ms,
        **trace,
    )
