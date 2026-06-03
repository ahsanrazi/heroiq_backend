from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://heroiq:heroiq_password@localhost:5432/heroiq"

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "heroiq-search"

    # OpenAI
    OPENAI_API_KEY: str = ""

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

    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    MIN_CHUNK_SIZE: int = 50

    # Search
    SEARCH_TOP_K: int = 5
    SEARCH_RESULTS_LIMIT: int = 3

    # Sentry
    SENTRY_DSN: str = ""

    # CORS — comma-separated list of allowed browser origins.
    # Empty (default) denies all cross-origin browser calls. Server-to-server callers are unaffected.
    ALLOWED_ORIGINS: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
