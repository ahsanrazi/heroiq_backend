from fastapi import APIRouter

from app.api.v1 import health, index, search

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(search.router, tags=["Search"])
api_router.include_router(index.router, tags=["Indexing"])
