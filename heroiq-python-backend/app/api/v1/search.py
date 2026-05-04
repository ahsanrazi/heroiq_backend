import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.api.deps import get_current_tenant, get_db
from app.core.rate_limiter import limiter
from app.models.tenant import Tenant
from app.schemas.search import SearchRequest, SearchResponse
from app.services.search_service import search_pages

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
@limiter.limit("60/minute")
async def ai_search(
    request: Request,
    body: SearchRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """AI search — embed query, search Pinecone, return pre-built search cards. No LLM call."""
    start = time.time()

    results = await search_pages(
        query=body.query,
        tenant_id=str(tenant.id),
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
