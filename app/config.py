from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://heroiq:heroiq_password@localhost:5432/heroiq"
    # Direct (non-pooler) URL used ONLY for Alembic migrations. DDL must not run
    # through a PgBouncer transaction pooler. Empty → fall back to DATABASE_URL
    # (correct for local dev, where DATABASE_URL is already a direct connection).
    DIRECT_URL: str = ""
    # SQLAlchemy connection pool, per process. Each gunicorn/Arq worker holds its
    # own pool, so real Postgres usage = (web workers + arq) × (size + overflow)
    # UNLESS a PgBouncer pooler fronts the DB (then the pooler's size is the cap).
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "heroiq-search"

    # OpenAI
    OPENAI_API_KEY: str = ""
    # Dedicated key for the brand-color (logo) endpoints — keeps their OpenAI
    # usage/billing isolated from search + indexing. Falls back to
    # OPENAI_API_KEY when unset (see `openai_logo_key`).
    OPENAI_API_KEY_LOGO: str = ""

    # Redis (Arq job queue broker). Local default; in production use the DO
    # Managed Valkey TLS string, e.g. rediss://default:<pwd>@host:25061
    REDIS_URL: str = "redis://localhost:6379"

    # Worker tuning (only read by the Arq worker process, not the web service)
    WORKER_MAX_JOBS: int = 2        # max bulk jobs processed concurrently per worker
    WORKER_JOB_TIMEOUT: int = 1800  # seconds before a single bulk job is abandoned
    STALE_JOB_MINUTES: int = 30     # processing jobs older than this are swept to failed on startup

    # Internal service-to-service auth — shared secret set to the SAME value on
    # both this app and the Next.js app. Empty = fail closed (all calls rejected).
    HEROIQ_INTERNAL_API_TOKEN: str = ""

    # App
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Chunking. Smaller windows give more focused chunks → sharper matches for
    # short site-search queries against long-form pages. MIN_CHUNK_SIZE only
    # drops the redundant trailing tail; the first/only window is always kept
    # (chunking_service.chunk_text) so short pages are never lost.
    CHUNK_SIZE: int = 250
    CHUNK_OVERLAP: int = 40
    MIN_CHUNK_SIZE: int = 50

    # Search
    # Chunks fetched from Pinecone per query BEFORE dedup-to-page. Kept well above
    # the 3 results shown: a content-heavy page can be many chunks, so a single
    # page can occupy several of the top-k slots — fetch enough that dedup still
    # yields 3 distinct pages. The number of results returned is caller-driven
    # (SearchRequest.limit, default 3), not SEARCH_RESULTS_LIMIT (currently unused).
    SEARCH_TOP_K: int = 20
    SEARCH_RESULTS_LIMIT: int = 3

    # External-call retry (OpenAI + Pinecone). Transient errors (timeouts,
    # connection drops, 5xx, rate-limit) are retried with exponential backoff;
    # after these run out the call surfaces as a 503, not a 500. See
    # app/core/retry.py.
    EXTERNAL_RETRY_ATTEMPTS: int = 3
    EXTERNAL_RETRY_BACKOFF_MULTIPLIER: float = 0.5
    EXTERNAL_RETRY_BACKOFF_MAX: float = 8.0

    # Rate limiting (per-tenant safety net behind Next.js). Next.js does the
    # primary per-IP + per-tenant limiting in the widget proxy; this is a
    # defense-in-depth backstop that only trips on a runaway / compromised
    # caller (leaked service token, retry loop). Limits sit ABOVE the Next.js
    # per-tenant ceilings so normal traffic never trips them.
    #   - Token bucket per (tenant, category). Sustained rate = PER_MIN/60 per
    #     second, with BURST capacity for short spikes.
    #   - Keyed on X-Tenant-Id only (Python sees the Next.js server IP, so
    #     per-IP keying is meaningless server-to-server).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_FAIL_OPEN: bool = True   # Redis error => allow (availability > strictness)
    RL_SEARCH_PER_MIN: int = 1200       # Next.js per-tenant search is 1000/min
    RL_SEARCH_BURST: int = 60
    RL_INDEX_PER_MIN: int = 120         # single-page save_post path
    RL_INDEX_BURST: int = 30
    RL_BULK_PER_MIN: int = 20           # full re-sync enqueues; a few/day is normal
    RL_BULK_BURST: int = 5
    RATE_LIMIT_KEY_PREFIX: str = "rl"   # isolates limiter keys from Arq's keys

    # Sentry
    SENTRY_DSN: str = ""

    # CORS — comma-separated list of allowed browser origins.
    # Empty (default) denies all cross-origin browser calls. Server-to-server callers are unaffected.
    ALLOWED_ORIGINS: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def openai_logo_key(self) -> str:
        """Key for the brand-color endpoints — dedicated logo key, or the shared
        OPENAI_API_KEY as a fallback if the logo key isn't configured."""
        return self.OPENAI_API_KEY_LOGO or self.OPENAI_API_KEY

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
