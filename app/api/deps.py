import hmac
from typing import Annotated, Callable, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.models.tenant import Tenant
from app.services.rate_limiter import check_rate_limit


async def get_db():
    """Yield an async database session."""
    async for session in get_session():
        yield session


async def require_service_token(
    x_internal_token: Annotated[Optional[str], Header()] = None,
) -> None:
    """Authenticate the CALLER (Next.js), not the tenant.

    Compares the X-Internal-Token header against the shared secret
    HEROIQ_INTERNAL_API_TOKEN (same value configured on both the Next.js app
    and this app). Constant-time comparison to avoid timing leaks.

    Fail closed: a missing server-side secret, a missing header, or a mismatch
    all reject. This is the single gate that says "only HeroIQ's own backend
    may call these endpoints" — the tenant identity is carried separately as
    data (X-Tenant-Id / path param).
    """
    expected = settings.HEROIQ_INTERNAL_API_TOKEN
    if not expected or not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "SERVICE_UNAUTHORIZED", "message": "Invalid service token."}},
        )


async def get_active_tenant_id(
    x_tenant_id: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Resolve the tenant for a tenant-scoped call from the X-Tenant-Id header.

    Authentication of the caller is handled separately by require_service_token
    (applied at the router level). This dependency only confirms the asserted
    tenant exists and is ACTIVE — defense-in-depth against a Next.js bug, and a
    cheap indexed primary-key read. Status is the Prisma TenantStatus enum
    stored as uppercase text.
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "MISSING_TENANT", "message": "X-Tenant-Id header is required."}},
        )

    result = await db.execute(
        select(Tenant).where(
            Tenant.id == x_tenant_id,
            Tenant.status == "ACTIVE",
        )
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "TENANT_INACTIVE", "message": "Unknown or inactive tenant."}},
        )

    return str(tenant.id)


def rate_limited(category: str) -> Callable:
    """Build a dependency that enforces the per-tenant rate limit for a category.

    Resolves the tenant first (reusing get_active_tenant_id — FastAPI caches it
    per-request so the tenant lookup runs once), then consumes one token from
    the tenant's bucket. Returns the tenant_id so endpoints keep the same
    `tenant_id: str = Depends(...)` shape. Raises 429 when the bucket is empty.

    Categories: "search", "index", "bulk" (see Settings.RL_* limits).
    """

    async def _dep(tenant_id: str = Depends(get_active_tenant_id)) -> str:
        await check_rate_limit(tenant_id, category)
        return tenant_id

    return _dep
