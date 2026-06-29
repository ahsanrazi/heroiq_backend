from fastapi import APIRouter, Depends

from app.api.deps import require_service_token
from app.api.v1 import brand, health, index, search

api_router = APIRouter()

# Health is intentionally open (liveness/readiness probe).
api_router.include_router(health.router, tags=["Health"])

# Search + indexing require the shared service token — only the HeroIQ Next.js
# backend may call these. Tenant identity is carried as data, not as auth.
api_router.include_router(search.router, tags=["Search"], dependencies=[Depends(require_service_token)])
api_router.include_router(index.router, tags=["Indexing"], dependencies=[Depends(require_service_token)])

# Brand-color extraction — service-token gated like the above, but NO
# ACTIVE-tenant requirement (runs during onboarding while tenant is PENDING).
api_router.include_router(brand.router, tags=["Branding"], dependencies=[Depends(require_service_token)])
