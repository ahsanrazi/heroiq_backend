import asyncio
import logging
from functools import partial

from pinecone import Pinecone

from app.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.core.retry import PINECONE_RETRYABLE, pinecone_retry

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
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


@pinecone_retry
async def _run_sync_retry(func, *args, **kwargs):
    """_run_sync with retries on transient Pinecone errors."""
    return await _run_sync(func, *args, **kwargs)


async def _pinecone_call(func, *args, **kwargs):
    """Run a Pinecone op with retries; surface exhausted failures as a 503
    rather than letting the raw SDK error leak out as an HTTP 500."""
    try:
        return await _run_sync_retry(func, *args, **kwargs)
    except PINECONE_RETRYABLE as e:
        logger.error(f"Pinecone call failed after retries: {e}")
        raise ServiceUnavailableError("Search index") from e


async def upsert_vectors(
    tenant_id: str,
    vectors: list[dict],
):
    """Upsert vectors into the tenant's Pinecone namespace."""
    index = _get_index()
    namespace = get_namespace(tenant_id)
    await _pinecone_call(index.upsert, vectors=vectors, namespace=namespace)


async def query_vectors(
    tenant_id: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Query Pinecone for similar vectors. Returns matches with metadata."""
    index = _get_index()
    namespace = get_namespace(tenant_id)

    results = await _pinecone_call(
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


def _delete_by_prefix(index, prefix: str, namespace: str) -> int:
    """List every vector ID sharing `prefix` in the namespace and delete them.

    Runs synchronously (called via _run_sync) so the paginated list() generator
    and the batched deletes happen in one thread-pool job. Returns the count
    actually removed.
    """
    ids: list[str] = []
    for id_batch in index.list(prefix=prefix, namespace=namespace):
        for item in id_batch:
            # Newer Pinecone SDK (>=6) yields ListItem objects exposing .id;
            # older versions yield plain string IDs. Normalize to strings so the
            # delete payload stays JSON-serializable.
            ids.append(item.id if hasattr(item, "id") else item)

    if not ids:
        return 0

    # Pinecone caps a delete-by-ids call at 1000 IDs.
    for start in range(0, len(ids), 1000):
        index.delete(ids=ids[start:start + 1000], namespace=namespace)
    return len(ids)


async def delete_vectors_by_page(tenant_id: str, wp_post_id: int) -> int:
    """Delete all chunk vectors for a page by discovering their real IDs.

    Serverless indexes don't support delete-by-metadata-filter, and the DB's
    chunk_count can drift, so we enumerate the actual vector IDs by their shared
    prefix `page_{wp_post_id}_chunk_` and delete those. The trailing `_chunk_`
    keeps `page_1_` from matching `page_10_`. Returns the number of vectors
    removed (0 if the page had none).
    """
    index = _get_index()
    namespace = get_namespace(tenant_id)
    prefix = f"page_{wp_post_id}_chunk_"
    return await _pinecone_call(_delete_by_prefix, index, prefix, namespace)


async def delete_namespace(tenant_id: str):
    """Delete the entire Pinecone namespace for a tenant."""
    index = _get_index()
    namespace = get_namespace(tenant_id)
    await _pinecone_call(index.delete, delete_all=True, namespace=namespace)


async def check_pinecone_health() -> str:
    """Check Pinecone connectivity."""
    try:
        index = _get_index()
        await _run_sync(index.describe_index_stats)
        return "connected"
    except Exception as e:
        logger.error(f"Pinecone health check failed: {e}")
        return "error"
