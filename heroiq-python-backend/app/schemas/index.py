from typing import Optional

from pydantic import BaseModel, Field


class IndexPageRequest(BaseModel):
    wp_post_id: int
    title: str = Field(..., max_length=500)
    url: str = Field(..., max_length=500)
    content: str = Field(..., min_length=1)
    post_type: str = Field(default="page", max_length=50)


class SearchCard(BaseModel):
    display_title: str
    summary: str
    recommended_cta: str
    page_url: str


class IndexPageResponse(BaseModel):
    status: str  # "indexed" or "skipped"
    wp_post_id: int
    chunk_count: Optional[int] = None
    search_card: Optional[SearchCard] = None
    reason: Optional[str] = None


class BulkIndexRequest(BaseModel):
    pages: list[IndexPageRequest] = Field(..., min_length=1)


class BulkIndexResponse(BaseModel):
    job_id: str
    status: str  # "queued"
    total_pages: int


class JobError(BaseModel):
    wp_post_id: int
    error: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # queued, processing, completed, failed
    total_pages: int
    pages_indexed: int
    pages_skipped: int
    pages_failed: int
    errors: list[JobError] = []
    duration_seconds: Optional[int] = None


class DeletePageResponse(BaseModel):
    success: bool
    wp_post_id: int
    chunks_removed: int


class DeleteTenantResponse(BaseModel):
    success: bool
    tenant_id: str
    pages_removed: int
    namespace_deleted: str
