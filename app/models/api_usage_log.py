import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String

from app.db.session import Base


class ApiUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("Tenant.id", ondelete="CASCADE"), nullable=False, index=True)
    operation = Column(String(30), nullable=False)
    model = Column(String(50), nullable=False)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Numeric(10, 6))
    created_at = Column(DateTime(timezone=False), default=datetime.utcnow, index=True)
