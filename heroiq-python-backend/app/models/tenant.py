"""Tenant model — READ-ONLY. Owned by Prisma in heroiq-super-admin/.
Python only reads id, serial_key (Postgres column "serialKey"), and status
for X-API-Key validation. Status is the Postgres enum TenantStatus, created
by Prisma — values: PENDING, ACTIVE, PAST_DUE, EXPIRED. We declare it with
create_type=False so SQLAlchemy never tries to (re)create the enum.
"""
from sqlalchemy import Column, Enum, String

from app.db.session import Base

TENANT_STATUS = Enum(
    "PENDING",
    "ACTIVE",
    "PAST_DUE",
    "EXPIRED",
    name="TenantStatus",
    create_type=False,
)


class Tenant(Base):
    __tablename__ = "Tenant"

    id = Column(String, primary_key=True)
    serial_key = Column("serialKey", String, unique=True, nullable=False)
    status = Column(TENANT_STATUS, nullable=False)
    plugin_site_url = Column("pluginSiteUrl", String)
