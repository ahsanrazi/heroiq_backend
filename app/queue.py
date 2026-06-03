"""Arq Redis pool used by the WEB service to enqueue background indexing jobs.

The web service only ever *pushes* jobs here; the actual work runs in the
separate Arq worker process (see app/worker.py). A single pool is created
lazily and reused across requests.
"""
import logging

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

# Arq task names — keep in sync with the functions registered in app/worker.py.
BULK_INDEX_TASK = "run_bulk_index"

_pool = None


def redis_settings() -> RedisSettings:
    """Build Arq RedisSettings from REDIS_URL (handles redis:// and rediss:// TLS)."""
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def get_redis_pool():
    """Lazily create and reuse a single Arq Redis pool for enqueuing jobs."""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
        logger.info("Arq enqueue pool created")
    return _pool


async def close_redis_pool():
    """Close the pool on app shutdown (called from the FastAPI lifespan)."""
    global _pool
    if _pool is not None:
        # redis-py >=5 uses aclose(); older versions expose close().
        close = getattr(_pool, "aclose", None) or _pool.close
        await close()
        _pool = None
        logger.info("Arq enqueue pool closed")
