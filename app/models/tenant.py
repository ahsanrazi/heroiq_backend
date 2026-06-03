"""Tenant model — READ-ONLY. Owned by Prisma in heroiq-super-admin/.
Python only reads id and status to confirm a tenant exists and is ACTIVE
(see get_active_tenant_id). Authentication of callers is handled by a shared
service token, not the tenant's serial key, so the serialKey column is no
longer mapped here. Status is the Postgres enum TenantStatus, created by
Prisma — values: PENDING, ACTIVE, PAST_DUE, EXPIRED. We declare it with
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
    status = Column(TENANT_STATUS, nullable=False)
    plugin_site_url = Column("pluginSiteUrl", String)
