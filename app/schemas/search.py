from typing import Optional

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
    matched_chunk: str = ""


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    results_count: int
    response_time_ms: int


class DebugMatch(BaseModel):
    """One raw Pinecone match, before dedup and truncation.

    Every metadata field is Optional and read with .get() in the service layer.
    The live search path uses bracket access (meta["display_title"]) and raises
    KeyError -> HTTP 500 on a vector missing a key. Debug must *show* you that
    vector instead of crashing on it.
    """

    id: str
    score: float  # RAW — the live path rounds to 2dp, which hides near-ties.

    # How the live search funnel would treat this match.
    live_rank: Optional[int] = None  # rank among dedup winners; None = lost dedup
    survives_dedup: bool = False  # best-scoring chunk for its page

    wp_post_id: Optional[int] = None
    display_title: Optional[str] = None
    page_title: Optional[str] = None  # raw WP title; differs from display_title
    chunk_index: Optional[int] = None
    chunk_text: Optional[str] = None
    page_url: Optional[str] = None
    post_type: Optional[str] = None


class DebugSearchResponse(BaseModel):
    query: str
    tenant_id: str
    namespace: str  # tenant_{id} — confirms which namespace was actually hit
    top_k: int
    match_count: int
    distinct_pages: int
    embed_tokens: int
    response_time_ms: int
    matches: list[DebugMatch]
