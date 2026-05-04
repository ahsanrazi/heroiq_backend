from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.tenant import Tenant


async def get_db():
    """Yield an async database session."""
    async for session in get_session():
        yield session


async def get_current_tenant(
    x_api_key: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Validate X-API-Key header against Tenant.serialKey (plaintext, matches
    how Next.js validates the same key in /api/plugin/config?key=...). The
    tenant must be ACTIVE — Prisma stores the TenantStatus enum as uppercase
    text.
    """
    result = await db.execute(
        select(Tenant).where(
            Tenant.serial_key == x_api_key,
            Tenant.status == "ACTIVE",
        )
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or inactive API key."}},
        )

    return tenant
