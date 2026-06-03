"""Arq worker entrypoint — runs bulk indexing OUT of the web process.

Run with:  arq app.worker.WorkerSettings

This process shares the same Docker image and code as the web service but
serves no HTTP. It pulls jobs from Redis and runs the heavy indexing work
(chunk -> embed -> LLM card -> Pinecone upsert), so search workers are never
blocked by a long bulk sync.

All module-level clients (Pinecone, AsyncOpenAI, the SQLAlchemy async engine /
session factory) initialize purely from env vars, so they re-create cleanly in
this separate process with no request context required.
"""
import logging
from datetime import datetime, timedelta

from arq.connections import RedisSettings
from sqlalchemy import select, update

from app.config import settings
from app.db.session import async_session_factory
from app.models.indexing_job import IndexingJob
from app.queue import redis_settings
from app.schemas.index import IndexPageRequest
from app.services.index_service import run_bulk_index_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_bulk_index(ctx, job_id: str, tenant_id: str, pages: list[dict]):
    """Arq task. `pages` arrives as plain dicts (Arq-serialized); rebuild models."""
    logger.info("[worker] bulk index start job=%s tenant=%s pages=%d", job_id, tenant_id, len(pages))
    page_objs = [IndexPageRequest(**p) for p in pages]
    await run_bulk_index_job(job_id=job_id, tenant_id=tenant_id, pages=page_objs)
    logger.info("[worker] bulk index done job=%s tenant=%s", job_id, tenant_id)


async def sweep_stale_jobs(ctx):
    """on_startup: any job stuck in 'processing' past STALE_JOB_MINUTES was
    orphaned by a prior worker crash/deploy — promote it to 'failed' so it
    doesn't hang the dashboard/plugin progress UI forever."""
    cutoff = datetime.utcnow() - timedelta(minutes=settings.STALE_JOB_MINUTES)
    async with async_session_factory() as db:
        result = await db.execute(
            select(IndexingJob.id).where(
                IndexingJob.status == "processing",
                IndexingJob.started_at < cutoff,
            )
        )
        stale_ids = [row[0] for row in result.all()]
        if not stale_ids:
            return
        await db.execute(
            update(IndexingJob)
            .where(IndexingJob.id.in_(stale_ids))
            .values(status="failed", completed_at=datetime.utcnow())
        )
        await db.commit()
        logger.warning("[worker] swept %d stale 'processing' jobs to failed: %s", len(stale_ids), stale_ids)


class WorkerSettings:
    """Arq reads this class. `arq app.worker.WorkerSettings`."""

    functions = [run_bulk_index]
    redis_settings: RedisSettings = redis_settings()
    max_jobs = settings.WORKER_MAX_JOBS
    job_timeout = settings.WORKER_JOB_TIMEOUT
    max_tries = 3
    keep_result = 3600
    on_startup = sweep_stale_jobs
