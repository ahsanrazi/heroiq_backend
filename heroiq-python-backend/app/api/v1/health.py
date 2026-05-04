from fastapi import APIRouter

from app.config import settings
from app.schemas.health import HealthResponse
from app.services.pinecone_service import check_pinecone_health
from app.services.embedding_service import check_openai_health
from app.db.session import check_db_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check — no auth required. Checks database, Pinecone, and OpenAI connectivity."""
    from datetime import datetime, timezone

    db_status = await check_db_health()
    pinecone_status = await check_pinecone_health()
    openai_status = await check_openai_health()

    all_healthy = all(s == "connected" for s in [db_status, pinecone_status, openai_status])

    return HealthResponse(
        status="healthy" if all_healthy else "unhealthy",
        version=settings.APP_VERSION,
        timestamp=datetime.now(timezone.utc),
        services={
            "database": db_status,
            "pinecone": pinecone_status,
            "openai": openai_status,
        },
    )
