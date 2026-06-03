from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_active_tenant_id, get_db
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
async def index_page(
    body: IndexPageRequest,
    tenant_id: str = Depends(get_active_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Index or update a single page. Skips if content hash unchanged."""
    result = await index_single_page(
        page_data=body,
        tenant_id=tenant_id,
        db=db,
    )
    return result


@router.post("/index/bulk", response_model=BulkIndexResponse, status_code=202)
async def bulk_index(
    body: BulkIndexRequest,
    tenant_id: str = Depends(get_active_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Accept pages array, enqueue to the worker, return job_id immediately."""
    job = await process_bulk_index(
        pages=body.pages,
        tenant_id=tenant_id,
        db=db,
    )
    return job


@router.get("/index/status/{job_id}", response_model=JobStatusResponse)
async def indexing_status(
    job_id: str,
    tenant_id: str = Depends(get_active_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Poll bulk indexing progress."""
    status = await get_job_status(job_id=job_id, tenant_id=tenant_id, db=db)
    if not status:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "JOB_NOT_FOUND", "message": f"Job {job_id} not found for this tenant."}},
        )
    return status


@router.delete("/index/{wp_post_id}", response_model=DeletePageResponse)
async def delete_page(
    wp_post_id: int,
    tenant_id: str = Depends(get_active_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a single page from the index (Pinecone + DB)."""
    result = await delete_page_index(
        wp_post_id=wp_post_id,
        tenant_id=tenant_id,
        db=db,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "PAGE_NOT_FOUND", "message": f"Page {wp_post_id} is not indexed for this tenant."}},
        )
    return result


@router.delete("/index/tenant/{tenant_id}", response_model=DeleteTenantResponse)
async def delete_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Wipe entire tenant index — Pinecone namespace + all content_pages rows.

    Admin/cross-tenant action: authenticated solely by the router-level
    service-token gate (require_service_token), NOT by a per-tenant key. It
    deliberately does NOT require the tenant to be ACTIVE — the common reason
    to wipe is that the tenant churned/expired. The caller (the Next.js
    super-admin delete flow) is the authority for which tenant_id to wipe.
    """
    result = await delete_tenant_index(tenant_id=tenant_id, db=db)
    return result
