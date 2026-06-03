from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init Sentry if DSN provided
    if settings.SENTRY_DSN:
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)
    yield
    # Shutdown: close the Arq enqueue pool if it was opened
    from app.queue import close_redis_pool

    await close_redis_pool()


app = FastAPI(
    title="HeroIQ AI Backend",
    description="Content indexing and AI search API for HeroIQ multi-tenant WordPress plugin",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# CORS — deny-by-default. All callers are server-to-server (Next.js → Python),
# which doesn't go through CORS. ALLOWED_ORIGINS env var opens specific browser origins if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Internal-Token", "X-Tenant-Id", "Authorization"],
)

# Exception handlers
register_exception_handlers(app)

# Routes
app.include_router(api_router, prefix="/api")
