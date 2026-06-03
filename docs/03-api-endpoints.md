# HeroIQ Python Backend — API Endpoints

**Production Base URL:** `https://hammerhead-app-f9fjz.ondigitalocean.app/api`
**Planned custom domain:** `https://ai.heroiq.io/api` (DNS not yet configured — switch when DNS is mapped)
**Auth:** API key via `X-API-Key` header (except health check)
**Total:** 7 endpoints across 3 categories

**Common Headers:**
```
X-API-Key: <tenant serial key — 64-hex-char string or legacy HIQ-XXXXXX-XXXXXX>
Content-Type: application/json
```

> **Note on rate limits:** the "Rate Limit" values shown on individual endpoints below are **design intent only**. No rate-limit middleware is currently active in the code. SlowAPI is not installed, and the per-IP rate limiter that used to exist was removed in commit `8a14fe2`. OpenAI and Pinecone upstream limits apply naturally; everything else is unthrottled.

---

## 1. Content Indexing

### `POST /api/index` — Index single page

Index or update a single page. Generates embeddings + GPT-4o-mini search card. Skips processing if content hash is unchanged.

**Rate Limit (design intent, not enforced):** 10 req/min per tenant.

```json
// Request
{
    "wp_post_id": 42,
    "title": "Root Canal Treatment",
    "url": "/services/root-canal-treatment",
    "content": "Expert root canal therapy with minimal discomfort using the latest dental technology...",
    "post_type": "page"
}

// Response 200 (indexed)
{
    "status": "indexed",
    "wp_post_id": 42,
    "chunk_count": 3,
    "search_card": {
        "display_title": "Root Canal Treatment",
        "summary": "Expert root canal therapy with minimal discomfort using the latest dental technology.",
        "recommended_cta": "Book a Consultation",
        "page_url": "/services/root-canal-treatment"
    }
}

// Response 200 (skipped — content unchanged)
{
    "status": "skipped",
    "wp_post_id": 42,
    "reason": "content_unchanged"
}
```

### `POST /api/index/bulk` — Index entire site (background job)

Accepts an array of pages and processes them in the background. Returns a `job_id` immediately for progress polling.

**Rate Limit (design intent, not enforced):** 10 req/min per tenant.

```json
// Request
{
    "pages": [
        {
            "wp_post_id": 42,
            "title": "Root Canal Treatment",
            "url": "/services/root-canal-treatment",
            "content": "Expert root canal therapy with minimal discomfort...",
            "post_type": "page"
        },
        {
            "wp_post_id": 55,
            "title": "Teeth Whitening",
            "url": "/services/teeth-whitening",
            "content": "Professional teeth whitening services...",
            "post_type": "page"
        }
        // ... more pages
    ]
}

// Response 202 (accepted, processing in background)
{
    "job_id": "job_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": "queued",
    "total_pages": 202
}
```

### `GET /api/index/status/{job_id}` — Bulk indexing progress

Poll this endpoint to track bulk indexing progress.

```json
// Response 200 (in progress)
{
    "job_id": "job_a1b2c3d4-...",
    "status": "processing",
    "total_pages": 202,
    "pages_indexed": 85,
    "pages_skipped": 12,
    "pages_failed": 1,
    "errors": [
        { "wp_post_id": 91, "error": "Empty content" }
    ]
}

// Response 200 (completed)
{
    "job_id": "job_a1b2c3d4-...",
    "status": "completed",
    "total_pages": 202,
    "pages_indexed": 185,
    "pages_skipped": 16,
    "pages_failed": 1,
    "errors": [
        { "wp_post_id": 91, "error": "Empty content" }
    ],
    "duration_seconds": 174
}
```

### `DELETE /api/index/{wp_post_id}` — Remove single page from index

Deletes all vectors for this page from Pinecone and removes the row from `content_pages`.

```json
// Response 200
{
    "success": true,
    "wp_post_id": 42,
    "chunks_removed": 3
}

// Error 404
{
    "error": {
        "code": "PAGE_NOT_FOUND",
        "message": "Page 42 is not indexed for this tenant."
    }
}
```

### `DELETE /api/index/tenant/{tenant_id}` — Wipe entire tenant index

Deletes the entire Pinecone namespace for the tenant and removes all `content_pages` rows. Used when a tenant is cancelled or needs a complete re-index from scratch.

```json
// Response 200
{
    "success": true,
    "tenant_id": "a1b2c3d4-...",
    "pages_removed": 202,
    "namespace_deleted": "tenant_a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

## 2. Search

### `POST /api/search` — AI search query

Core endpoint. Called by Next.js after credit verification. Embeds the query and searches Pinecone — **no LLM call**, returns pre-built search cards from Pinecone metadata.

**Rate Limit (design intent, not enforced):** 60 req/min per tenant.

```json
// Request
{
    "query": "best dentist for root canal",
    "limit": 3
}

// Response 200
{
    "results": [
        {
            "wp_post_id": 42,
            "display_title": "Root Canal Treatment",
            "summary": "Expert root canal therapy with minimal discomfort using the latest dental technology.",
            "recommended_cta": "Book a Consultation",
            "page_url": "/services/root-canal-treatment",
            "score": 0.94,
            "matched_chunk": "Our root canal treatment uses the latest rotary endodontic technology to ensure a comfortable, virtually pain-free experience. Most patients return to normal activities the same day..."
        },
        {
            "wp_post_id": 15,
            "display_title": "Pain-Free Dentistry",
            "summary": "Modern techniques ensure comfortable dental procedures for anxious patients.",
            "recommended_cta": "Learn More",
            "page_url": "/services/pain-free-dentistry",
            "score": 0.87,
            "matched_chunk": "We specialize in anxiety-free dentistry. From sedation options to numbing techniques that work in seconds, our team is trained to keep nervous patients comfortable..."
        },
        {
            "wp_post_id": 8,
            "display_title": "Emergency Dental Services",
            "summary": "Same-day emergency appointments for urgent dental needs including root canals.",
            "recommended_cta": "Call Now",
            "page_url": "/services/emergency",
            "score": 0.72,
            "matched_chunk": "Emergency root canals available 7 days a week. Walk-ins welcome — call us and we will see you the same day for any acute dental pain or infection..."
        }
    ],
    "query": "best dentist for root canal",
    "results_count": 3,
    "response_time_ms": 260
}

// `matched_chunk`: text of the highest-scoring Pinecone chunk for this page (≤1000 chars).
// Useful for displaying excerpts in the UI, debugging poor matches, and result tuning.

// Response 200 (no results)
{
    "results": [],
    "query": "something completely unrelated",
    "results_count": 0,
    "response_time_ms": 180
}
```

---

## 3. Health

### `GET /api/health` — Health check

**Auth:** None

```json
// Response 200
{
    "status": "healthy",
    "version": "1.0.0",
    "timestamp": "2026-04-02T10:00:00Z",
    "services": {
        "database": "connected",
        "pinecone": "connected",
        "openai": "connected"
    }
}

// Response 503 (unhealthy)
{
    "status": "unhealthy",
    "version": "1.0.0",
    "timestamp": "2026-04-02T10:00:00Z",
    "services": {
        "database": "connected",
        "pinecone": "error",
        "openai": "connected"
    }
}
```

---

## 4. Endpoint Summary

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/api/index` | API Key | Index single page |
| POST | `/api/index/bulk` | API Key | Index entire site (background) |
| GET | `/api/index/status/{job_id}` | API Key | Bulk indexing progress |
| DELETE | `/api/index/{wp_post_id}` | API Key | Remove one page from index |
| DELETE | `/api/index/tenant/{tenant_id}` | API Key | Wipe entire tenant index |
| POST | `/api/search` | API Key | Search query → full results with cards |
| GET | `/api/health` | None | Health check |

---

## 5. Error Responses

All errors follow this format:

```json
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable message"
    }
}
```

| Code | Status | Meaning |
|------|--------|---------|
| 400 | Bad Request | Validation error (missing fields, invalid data) |
| 401 | Unauthorized | Missing or invalid API key |
| 404 | Not Found | Resource doesn't exist (page, job, tenant) |
| 429 | Too Many Requests | Rate limited — reserved for the future; not currently returned by Python (no rate-limit middleware is active). |
| 500 | Internal Server Error | Server error |
| 503 | Service Unavailable | External service down (Pinecone, OpenAI) |
