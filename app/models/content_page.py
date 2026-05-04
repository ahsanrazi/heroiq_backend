import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db.session import Base


class ContentPage(Base):
    __tablename__ = "content_pages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("Tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    wp_post_id = Column(BigInteger, nullable=False)
    page_title = Column(String(500), nullable=False)
    page_url = Column(String(500), nullable=False)
    post_type = Column(String(50), default="page")
    content_hash = Column(String(64), nullable=False)
    chunk_count = Column(Integer, default=0)
    is_indexed = Column(Boolean, default=False)
    last_indexed_at = Column(DateTime(timezone=False))
    created_at = Column(DateTime(timezone=False), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=False), default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "wp_post_id", name="unique_tenant_page"),
    )
