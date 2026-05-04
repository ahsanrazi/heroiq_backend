from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.core.rate_limiter import limiter
from app.models.tenant import Tenant
from app.schemas.index import (
    BulkIndexRequest,
    BulkIndexResponse,
    DeletePageResponse,
    DeleteTenantResponse,
    IndexPageRequest,
    IndexPageResponse,
    JobStatusResponse,
)
from app.services.index_service import (
    delete_page_index,
    delete_tenant_index,
    get_job_status,
    index_single_page,
    process_bulk_index,
)

router = APIRouter()


@router.post("/index", response_model=IndexPageResponse)
@limiter.limit("10/minute")
async def index_page(
    request: Request,
    body: IndexPageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Index or update a single page. Skips if content hash unchanged."""
    result = await index_single_page(
        page_data=body,
        tenant_id=str(tenant.id),
        db=db,
    )
    return result


@router.post("/index/bulk", response_model=BulkIndexResponse, status_code=202)
@limiter.limit("10/minute")
async def bulk_index(
    request: Request,
    body: BulkIndexRequest,
    background_tasks: BackgroundTasks,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Accept pages array, return job_id immediately, process in background."""
    job = await process_bulk_index(
        pages=body.pages,
        tenant_id=str(tenant.id),
        db=db,
        background_tasks=background_tasks,
    )
    return job


@router.get("/index/status/{job_id}", response_model=JobStatusResponse)
@limiter.limit("10/minute")
async def indexing_status(
    request: Request,
    job_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Poll bulk indexing progress."""
    status = await get_job_status(job_id=job_id, tenant_id=str(tenant.id), db=db)
    if not status:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found for this tenant."}},
        )
    return status


@router.delete("/index/{wp_post_id}", response_model=DeletePageResponse)
@limiter.limit("10/minute")
async def delete_page(
    request: Request,
    wp_post_id: int,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Remove a single page from the index (Pinecone + DB)."""
    result = await delete_page_index(
        wp_post_id=wp_post_id,
        tenant_id=str(tenant.id),
        db=db,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "PAGE_NOT_FOUND", "message": f"Page {wp_post_id} is not indexed for this tenant."}},
        )
    return result


@router.delete("/index/tenant/{tenant_id}", response_model=DeleteTenantResponse)
@limiter.limit("10/minute")
async def delete_tenant(
    request: Request,
    tenant_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Wipe entire tenant index — Pinecone namespace + all content_pages rows."""
    result = await delete_tenant_index(tenant_id=tenant_id, db=db)
    return result
