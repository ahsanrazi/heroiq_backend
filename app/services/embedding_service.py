import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


async def generate_embedding(text: str) -> dict:
    """Generate a 1536-dim embedding for the given text using text-embedding-3-small.
    Returns {"embedding": [...], "usage_tokens": int}
    """
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return {
        "embedding": response.data[0].embedding,
        "usage_tokens": response.usage.total_tokens,
    }


async def generate_embeddings_batch(texts: list[str]) -> dict:
    """Generate embeddings for a batch of texts in a single API call.
    Returns {"embeddings": [[...], ...], "usage_tokens": int}
    """
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
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
