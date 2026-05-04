from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=3, ge=1, le=10)


class SearchResult(BaseModel):
    wp_post_id: int
    display_title: str
    summary: str
    recommended_cta: str
    page_url: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    results_count: int
    response_time_ms: int
