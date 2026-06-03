import hashlib
import logging
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.api_usage_log import ApiUsageLog
from app.models.content_page import ContentPage
from app.models.indexing_job import IndexingJob
from app.queue import BULK_INDEX_TASK, get_redis_pool
from app.schemas.index import (
    BulkIndexResponse,
    DeletePageResponse,
    DeleteTenantResponse,
    IndexPageRequest,
    IndexPageResponse,
    JobStatusResponse,
    SearchCard,
)
from app.services.chunking_service import chunk_text
from app.services.embedding_service import generate_embeddings_batch
from app.services.llm_service import generate_search_card
from app.services.openai_pricing import calc_cost
from app.services.pinecone_service import (
    delete_namespace,
    delete_vectors_by_page,
    upsert_vectors,
)

logger = logging.getLogger(__name__)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def _log_usage(db: AsyncSession, tenant_id: str, operation: str, model: str, input_tokens: int, output_tokens: int = 0, cost_usd: float = 0.0):
    """Log OpenAI API usage to api_usage_logs table."""
    log = ApiUsageLog(
        tenant_id=tenant_id,
        operation=operation,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    db.add(log)


async def index_single_page(
    page_data: IndexPageRequest,
    tenant_id: str,
    db: AsyncSession,
) -> IndexPageResponse:
    """Index a single page: hash check → chunk → embed → LLM card → Pinecone upsert."""
    content_hash = _hash_content(page_data.content)

    # Check if already indexed with same hash
    result = await db.execute(
        select(ContentPage).where(
            ContentPage.tenant_id == tenant_id,
            ContentPage.wp_post_id == page_data.wp_post_id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.content_hash == content_hash:
        return IndexPageResponse(
            status="skipped",
            wp_post_id=page_data.wp_post_id,
            reason="content_unchanged",
        )

    # If re-indexing, delete old vectors first (handles chunk count changes)
    if existing and existing.chunk_count:
        await delete_vectors_by_page(tenant_id, page_data.wp_post_id, existing.chunk_count)

    # Chunk content
    chunks = chunk_text(page_data.content)

    # Generate embeddings for all chunks
    embed_result = await generate_embeddings_batch(chunks)
    embeddings = embed_result["embeddings"]

    # Log embedding usage
    await _log_usage(
        db, tenant_id,
        operation="index_embed",
        model="text-embedding-3-small",
        input_tokens=embed_result["usage_tokens"],
        cost_usd=calc_cost("text-embedding-3-small", embed_result["usage_tokens"]),
    )

    # Generate search card via LLM
    card_data = await generate_search_card(title=page_data.title, content=page_data.content)

    # Log LLM usage
    await _log_usage(
        db, tenant_id,
        operation="index_generate",
        model="gpt-4o-mini",
        input_tokens=card_data["input_tokens"],
        output_tokens=card_data["output_tokens"],
        cost_usd=calc_cost("gpt-4o-mini", card_data["input_tokens"], card_data["output_tokens"]),
    )

    # Build Pinecone vectors
    vectors = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vectors.append({
            "id": f"page_{page_data.wp_post_id}_chunk_{i}",
            "values": embedding,
            "metadata": {
                "wp_post_id": page_data.wp_post_id,
                "page_title": page_data.title,
                "page_url": page_data.url,
                "post_type": page_data.post_type,
                "chunk_index": i,
                "chunk_text": chunk[:1000],
                "content_hash": content_hash,
                "display_title": card_data["display_title"],
                "summary": card_data["summary"],
                "recommended_cta": card_data["recommended_cta"],
            },
        })

    # Upsert to Pinecone
    await upsert_vectors(tenant_id=tenant_id, vectors=vectors)

    # Update or create content_pages row
    now = datetime.utcnow()
    if existing:
        existing.page_title = page_data.title
        existing.page_url = page_data.url
        existing.post_type = page_data.post_type
        existing.content_hash = content_hash
        existing.chunk_count = len(chunks)
        existing.is_indexed = True
        existing.last_indexed_at = now
        existing.updated_at = now
    else:
        page = ContentPage(
            tenant_id=tenant_id,
            wp_post_id=page_data.wp_post_id,
            page_title=page_data.title,
            page_url=page_data.url,
            post_type=page_data.post_type,
            content_hash=content_hash,
            chunk_count=len(chunks),
            is_indexed=True,
            last_indexed_at=now,
        )
        db.add(page)

    await db.commit()

    return IndexPageResponse(
        status="indexed",
        wp_post_id=page_data.wp_post_id,
        chunk_count=len(chunks),
        search_card=SearchCard(
            display_title=card_data["display_title"],
            summary=card_data["summary"],
            recommended_cta=card_data["recommended_cta"],
            page_url=page_data.url,
        ),
    )


async def process_bulk_index(
    pages: list[IndexPageRequest],
    tenant_id: str,
    db: AsyncSession,
) -> BulkIndexResponse:
    """Create indexing job, enqueue it to the Arq worker, return job_id immediately.

    Single-flight per tenant: if a bulk job for this tenant is already queued or
    processing, return that job instead of creating/enqueuing a duplicate. This
    keeps only one bulk run active per tenant at a time, which also prevents the
    concurrent delete-then-upsert race in index_single_page.
    """
    existing = await db.execute(
        select(IndexingJob)
        .where(
            IndexingJob.tenant_id == tenant_id,
            IndexingJob.status.in_(["queued", "processing"]),
        )
        .order_by(IndexingJob.started_at.desc())
        .limit(1)
    )
    active = existing.scalar_one_or_none()
    if active:
        return BulkIndexResponse(
            job_id=str(active.id),
            status=active.status,
            total_pages=active.total_pages,
        )

    job = IndexingJob(
        tenant_id=tenant_id,
        status="queued",
        total_pages=len(pages),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    job_id = str(job.id)

    # Hand off to the Arq worker process (separate from the web service).
    redis = await get_redis_pool()
    await redis.enqueue_job(
        BULK_INDEX_TASK,
        job_id,
        tenant_id,
        [p.model_dump() for p in pages],
    )

    return BulkIndexResponse(
        job_id=job_id,
        status="queued",
        total_pages=len(pages),
    )


async def run_bulk_index_job(
    job_id: str,
    tenant_id: str,
    pages: list[IndexPageRequest],
):
    """Worker task: process all pages one by one, detect deletions, update job progress.

    Runs in the Arq worker process. Wrapped so any unhandled error marks the job
    'failed' (instead of leaving it stuck 'processing' forever).
    """
    async with async_session_factory() as db:
        result = await db.execute(select(IndexingJob).where(IndexingJob.id == job_id))
        job = result.scalar_one()

        # started_at is DB-defaulted at row creation; reset it to the real
        # processing-start so get_job_status() duration excludes queue wait.
        job.status = "processing"
        job.started_at = datetime.utcnow()
        await db.commit()

        try:
            # Track incoming page IDs for deletion detection
            incoming_post_ids = {p.wp_post_id for p in pages}

            for page_data in pages:
                try:
                    response = await index_single_page(
                        page_data=page_data,
                        tenant_id=tenant_id,
                        db=db,
                    )

                    await db.refresh(job)

                    if response.status == "indexed":
                        job.pages_indexed += 1
                    elif response.status == "skipped":
                        job.pages_skipped += 1

                except Exception as e:
                    logger.error(f"Bulk index error for page {page_data.wp_post_id}: {e}")
                    await db.refresh(job)
                    job.pages_failed += 1
                    errors = job.errors or []
                    errors.append({"wp_post_id": page_data.wp_post_id, "error": str(e)})
                    job.errors = errors

                await db.commit()

            # Deletion detection: remove pages NOT in incoming list
            result = await db.execute(
                select(ContentPage).where(ContentPage.tenant_id == tenant_id)
            )
            all_indexed = result.scalars().all()

            for page in all_indexed:
                if page.wp_post_id not in incoming_post_ids:
                    logger.info(f"Deleting removed page {page.wp_post_id} for tenant {tenant_id}")
                    if page.chunk_count:
                        await delete_vectors_by_page(tenant_id, page.wp_post_id, page.chunk_count)
                    await db.delete(page)

            await db.commit()

            # Mark job completed
            await db.refresh(job)
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            await db.commit()

        except Exception as e:
            # Unhandled failure (e.g. Pinecone/OpenAI outage, DB error): mark the
            # job failed so the dashboard/plugin stops polling a dead job. Arq
            # will retry the task up to max_tries.
            logger.exception(f"Bulk index job {job_id} failed: {e}")
            await db.rollback()
            fail = (await db.execute(select(IndexingJob).where(IndexingJob.id == job_id))).scalar_one()
            fail.status = "failed"
            fail.completed_at = datetime.utcnow()
            errors = fail.errors or []
            errors.append({"job_error": str(e)})
            fail.errors = errors
            await db.commit()
            raise


async def get_job_status(job_id: str, tenant_id: str, db: AsyncSession) -> JobStatusResponse | None:
    """Get bulk indexing job progress."""
    result = await db.execute(
        select(IndexingJob).where(
            IndexingJob.id == job_id,
            IndexingJob.tenant_id == tenant_id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        return None

    duration = None
    if job.completed_at and job.started_at:
        duration = int((job.completed_at - job.started_at).total_seconds())

    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        total_pages=job.total_pages,
        pages_indexed=job.pages_indexed,
        pages_skipped=job.pages_skipped,
        pages_failed=job.pages_failed,
        errors=job.errors or [],
        duration_seconds=duration,
    )


async def delete_page_index(wp_post_id: int, tenant_id: str, db: AsyncSession) -> DeletePageResponse | None:
    """Delete a single page from Pinecone + content_pages."""
    result = await db.execute(
        select(ContentPage).where(
            ContentPage.tenant_id == tenant_id,
            ContentPage.wp_post_id == wp_post_id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        return None

    chunks_removed = page.chunk_count or 0

    # Delete from Pinecone
    await delete_vectors_by_page(tenant_id, wp_post_id, chunks_removed)

    # Delete from DB
    await db.delete(page)
    await db.commit()

    return DeletePageResponse(
        success=True,
        wp_post_id=wp_post_id,
        chunks_removed=chunks_removed,
    )


async def delete_tenant_index(tenant_id: str, db: AsyncSession) -> DeleteTenantResponse:
    """Wipe entire tenant index — Pinecone namespace + all content_pages rows."""
    # Count pages
    result = await db.execute(
        select(ContentPage).where(ContentPage.tenant_id == tenant_id)
    )
    pages = result.scalars().all()
    pages_removed = len(pages)

    # Delete Pinecone namespace
    await delete_namespace(tenant_id)

    # Delete all content_pages for tenant
    await db.execute(
        delete(ContentPage).where(ContentPage.tenant_id == tenant_id)
    )
    await db.commit()

    namespace = f"tenant_{tenant_id}"

    return DeleteTenantResponse(
        success=True,
        tenant_id=tenant_id,
        pages_removed=pages_removed,
        namespace_deleted=namespace,
    )
