import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.session import Base


class IndexingJob(Base):
    __tablename__ = "indexing_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("Tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="queued", index=True)
    total_pages = Column(Integer, default=0)
    pages_indexed = Column(Integer, default=0)
    pages_skipped = Column(Integer, default=0)
    pages_failed = Column(Integer, default=0)
    errors = Column(JSONB, default=list)
    started_at = Column(DateTime(timezone=False), default=datetime.utcnow)
    completed_at = Column(DateTime(timezone=False))
