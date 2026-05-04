from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str  # "healthy" or "unhealthy"
    version: str
    timestamp: datetime
    services: dict[str, str]  # {"database": "connected", "pinecone": "connected", ...}
