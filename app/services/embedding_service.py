import logging

from openai import AsyncOpenAI

from app.config import settings
from app.core.exceptions import ServiceUnavailableError
from app.core.retry import OPENAI_RETRYABLE, openai_retry

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


@openai_retry
async def _create_embedding(text_or_texts):
    """Raw embeddings call, retried on transient OpenAI errors."""
    return await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text_or_texts,
    )


async def generate_embedding(text: str) -> dict:
    """Generate a 1536-dim embedding for the given text using text-embedding-3-small.
    Returns {"embedding": [...], "usage_tokens": int}
    """
    try:
        response = await _create_embedding(text)
    except OPENAI_RETRYABLE as e:
        logger.error(f"OpenAI embedding failed after retries: {e}")
        raise ServiceUnavailableError("OpenAI") from e
    return {
        "embedding": response.data[0].embedding,
        "usage_tokens": response.usage.total_tokens,
    }


async def generate_embeddings_batch(texts: list[str]) -> dict:
    """Generate embeddings for a batch of texts in a single API call.
    Returns {"embeddings": [[...], ...], "usage_tokens": int}
    """
    try:
        response = await _create_embedding(texts)
    except OPENAI_RETRYABLE as e:
        logger.error(f"OpenAI batch embedding failed after retries: {e}")
        raise ServiceUnavailableError("OpenAI") from e
    return {
        "embeddings": [item.embedding for item in response.data],
        "usage_tokens": response.usage.total_tokens,
    }


async def check_openai_health() -> str:
    """Check OpenAI API connectivity."""
    try:
        await client.models.list()
        return "connected"
    except Exception as e:
        logger.error(f"OpenAI health check failed: {e}")
        return "error"
