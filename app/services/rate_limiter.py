"""Per-tenant rate limiting — a Redis-backed token bucket safety net.

This is defense-in-depth BEHIND the Next.js widget proxy, which already does
the primary per-IP + per-tenant limiting (see heroiq-super-admin
src/lib/rate-limit.ts). This backstop only trips on a runaway / compromised
caller (leaked HEROIQ_INTERNAL_API_TOKEN, a buggy retry loop, or a future
multi-instance Next.js where the in-memory counter no longer aggregates).

Design:
  - Token bucket per (tenant, category), evaluated atomically via a Lua script
    so the 4 Gunicorn workers don't race. Sustained rate = PER_MIN / 60 tokens
    per second; BURST is the bucket capacity for short spikes.
  - Keyed on X-Tenant-Id only. Python sees the Next.js server IP for every
    request, so per-IP keying would be meaningless here.
  - FAIL OPEN: any Redis error allows the request (availability > strictness).
    A Redis blip must never take down live search — Next.js stays the primary
    defense. Toggle with RATE_LIMIT_FAIL_OPEN.

A dedicated Redis client (separate from the Arq enqueue pool in app/queue.py)
keeps limiter keys isolated and avoids contention with the job queue.
"""
import logging
import time

from fastapi import HTTPException

from app.config import settings

try:  # redis ships transitively with the `arq` dependency
    from redis.asyncio import Redis
except Exception:  # pragma: no cover - redis missing in a stripped env
    Redis = None  # type: ignore

logger = logging.getLogger(__name__)

# KEYS[1] = bucket key
# ARGV: capacity (burst), rate (tokens/sec), now (epoch seconds), ttl (seconds)
# Returns {allowed (0|1), retry_after (seconds)}
_TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = math.ceil((1 - tokens) / rate)
  if retry_after < 1 then retry_after = 1 end
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], ttl)

return {allowed, retry_after}
"""

_client = None
_script = None


def _limits_for(category: str) -> tuple[int, int]:
    """Return (per_minute, burst) for a category, defaulting to search."""
    table = {
        "search": (settings.RL_SEARCH_PER_MIN, settings.RL_SEARCH_BURST),
        "index": (settings.RL_INDEX_PER_MIN, settings.RL_INDEX_BURST),
        "bulk": (settings.RL_BULK_PER_MIN, settings.RL_BULK_BURST),
    }
    return table.get(category, (settings.RL_SEARCH_PER_MIN, settings.RL_SEARCH_BURST))


async def get_rate_limit_client():
    """Lazily create and reuse a dedicated Redis client for rate limiting."""
    global _client, _script
    if _client is None:
        if Redis is None:
            raise RuntimeError("redis.asyncio is unavailable")
        _client = Redis.from_url(settings.REDIS_URL)
        _script = _client.register_script(_TOKEN_BUCKET_LUA)
        logger.info("Rate-limit Redis client created")
    return _client


async def close_rate_limit_client():
    """Close the client on app shutdown (called from the FastAPI lifespan)."""
    global _client, _script
    if _client is not None:
        # redis-py >=5 uses aclose(); older versions expose close().
        close = getattr(_client, "aclose", None) or _client.close
        await close()
        _client = None
        _script = None
        logger.info("Rate-limit Redis client closed")


async def _consume(key: str, capacity: int, rate: float, ttl: int) -> tuple[int, int]:
    """Run the token-bucket script. Returns (allowed, retry_after_seconds).

    Isolated so tests can monkeypatch the Redis interaction without a live
    Redis (and to exercise the fail-open path by raising here).
    """
    await get_rate_limit_client()
    result = await _script(keys=[key], args=[capacity, rate, time.time(), ttl])
    return int(result[0]), int(result[1])


async def check_rate_limit(tenant_id: str, category: str) -> None:
    """Consume one token for (tenant, category). Raise 429 if the bucket is empty.

    Fails open: on any Redis/client error the request is allowed when
    RATE_LIMIT_FAIL_OPEN is set (the default), with a warning logged.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    per_min, burst = _limits_for(category)
    rate = per_min / 60.0
    capacity = max(1, burst)
    ttl = (int(capacity / rate) + 60) if rate > 0 else 120
    key = f"{settings.RATE_LIMIT_KEY_PREFIX}:{category}:{tenant_id}"

    try:
        allowed, retry_after = await _consume(key, capacity, rate, ttl)
    except Exception as exc:
        logger.warning(
            "Rate limiter unavailable (category=%s tenant=%s): %s", category, tenant_id, exc
        )
        if settings.RATE_LIMIT_FAIL_OPEN:
            return
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "RATE_LIMITER_UNAVAILABLE", "message": "Rate limiter unavailable."}},
        )

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests for this tenant. Please retry shortly.",
                }
            },
            headers={"Retry-After": str(max(1, retry_after))},
        )
