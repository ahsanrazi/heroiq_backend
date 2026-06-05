"""Shared retry decorators for transient OpenAI / Pinecone failures.

Both external services occasionally return transient errors (timeouts, dropped
connections, 5xx, rate-limit). Without retries a single blip surfaces to the
caller as an HTTP 500. These decorators retry only the *transient* error types
with exponential backoff; permanent errors (bad request, auth) are NOT retried.

After the attempts run out the original exception is re-raised (reraise=True);
the service-layer wrappers translate that into a ServiceUnavailableError (503)
so the widget/Next.js can degrade gracefully.

Exception classes are imported defensively so this module loads even if a SDK
version moves/renames a class — anything that fails to import is simply dropped
from the retry set.
"""

import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

logger = logging.getLogger(__name__)


def _collect(*candidates) -> tuple:
    """Filter out any None entries (classes that failed to import)."""
    return tuple(c for c in candidates if c is not None)


# ---- OpenAI transient errors -------------------------------------------------
# Stable in the openai>=1.x SDK. Imported individually so one rename doesn't
# break the whole set.
try:
    from openai import APITimeoutError
except Exception:  # pragma: no cover - import guard
    APITimeoutError = None
try:
    from openai import APIConnectionError
except Exception:  # pragma: no cover
    APIConnectionError = None
try:
    from openai import InternalServerError
except Exception:  # pragma: no cover
    InternalServerError = None
try:
    from openai import RateLimitError
except Exception:  # pragma: no cover
    RateLimitError = None

# NOTE: RateLimitError (429) is retried with plain exponential backoff here.
# This is a defense-in-depth path behind Next.js's own limiter, so honoring the
# precise `Retry-After` header is a future refinement, not required now.
OPENAI_RETRYABLE = _collect(
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    RateLimitError,
)


# ---- Pinecone transient errors -----------------------------------------------
# Pinecone v5 raises subclasses of PineconeException. We retry on the base (it
# covers API + connection failures) plus generic transport errors. We avoid
# retrying obvious client errors where the class is identifiable.
try:
    from pinecone.exceptions import PineconeException
except Exception:  # pragma: no cover
    try:
        from pinecone.core.openapi.shared.exceptions import PineconeException  # type: ignore
    except Exception:  # pragma: no cover
        PineconeException = None

PINECONE_RETRYABLE = _collect(
    PineconeException,
    ConnectionError,   # builtin — covers urllib3/requests connection drops
    TimeoutError,      # builtin
)


def _make_decorator(retryable: tuple, label: str):
    """Build a tenacity retry decorator. If no retryable classes resolved
    (extremely defensive), return an identity decorator so calls still run."""
    if not retryable:
        logger.warning("No retryable exception types resolved for %s; retries disabled.", label)

        def _identity(func):
            return func

        return _identity

    return retry(
        stop=stop_after_attempt(settings.EXTERNAL_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=settings.EXTERNAL_RETRY_BACKOFF_MULTIPLIER,
            max=settings.EXTERNAL_RETRY_BACKOFF_MAX,
        ),
        retry=retry_if_exception_type(retryable),
        reraise=True,
    )


openai_retry = _make_decorator(OPENAI_RETRYABLE, "OpenAI")
pinecone_retry = _make_decorator(PINECONE_RETRYABLE, "Pinecone")
