import asyncio
import logging
from functools import partial

from pinecone import Pinecone

from app.config import settings

logger = logging.getLogger(__name__)

pc = Pinecone(api_key=settings.PINECONE_API_KEY)

_index = None


def _get_index():
    """Build the Pinecone index client once and reuse it for the process
    lifetime. Avoids reconstructing the client (host resolution + setup) on every
    upsert/query/delete call."""
    global _index
    if _index is None:
        _index = pc.Index(settings.PINECONE_INDEX_NAME)
    return _index


def get_namespace(tenant_id: str) -> str:
    """Return Pinecone namespace for a tenant: tenant_{uuid}"""
    return f"tenant_{tenant_id}"


async def _run_sync(func, *args, **kwargs):
    """Run a synchronous Pinecone call in the thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def upsert_vectors(
    tenant_id: str,
    vectors: list[dict],
):
    """Upsert vectors into the tenant's Pinecone namespace."""
    index = _get_index()
    namespace = get_namespace(tenant_id)
    await _run_sync(index.upsert, vectors=vectors, namespace=namespace)


async def query_vectors(
    tenant_id: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Query Pinecone for similar vectors. Returns matches with metadata."""
    index = _get_index()
    namespace = get_namespace(tenant_id)

    results = await _run_sync(
        index.query,
        vector=query_embedding,
        top_k=top_k,
        include_metadata=True,
        namespace=namespace,
    )

    return [
        {
            "id": match.id,
            "score": match.score,
            "metadata": match.metadata,
        }
        for match in results.matches
    ]


async def delete_vectors_by_page(tenant_id: str, wp_post_id: int, chunk_count: int):
    """Delete all chunk vectors for a specific page."""
    index = _get_index()
    namespace = get_namespace(tenant_id)

    ids = [f"page_{wp_post_id}_chunk_{i}" for i in range(chunk_count)]
    await _run_sync(index.delete, ids=ids, namespace=namespace)


async def delete_namespace(tenant_id: str):
    """Delete the entire Pinecone namespace for a tenant."""
    index = _get_index()
    namespace = get_namespace(tenant_id)
    await _run_sync(index.delete, delete_all=True, namespace=namespace)


async def check_pinecone_health() -> str:
    """Check Pinecone connectivity."""
    try:
        index = _get_index()
        await _run_sync(index.describe_index_stats)
        return "connected"
    except Exception as e:
        logger.error(f"Pinecone health check failed: {e}")
        return "error"
