import time

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, rate_limited
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import search_pages

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
