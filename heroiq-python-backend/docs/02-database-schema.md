# HeroIQ Python Backend — Database Schema

Two storage systems: **PostgreSQL** (shared database, Python owns 3 tables), **Pinecone** (vector embeddings).

> Python backend shares a PostgreSQL database with the Next.js backend. Python owns `content_pages`, `indexing_jobs`, and `api_usage_logs`. All other tables (tenants, config, billing, leads, analytics, etc.) are owned by Next.js.

---

## 1. PostgreSQL Tables (Python-owned)

### `content_pages` — Indexed content tracking

**Owned by:** Python backend

Tracks what content has been indexed per tenant. The `content_hash` field enables delta updates — on re-sync, compare hash. If unchanged, skip re-indexing.

```sql
CREATE TABLE content_pages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    wp_post_id      BIGINT NOT NULL,
    page_title      VARCHAR(500) NOT NULL,
    page_url        VARCHAR(500) NOT NULL,
    post_type       VARCHAR(50) DEFAULT 'page',
    content_hash    VARCHAR(64) NOT NULL,           -- SHA-256 for delta updates
    chunk_count     INTEGER DEFAULT 0,
    is_indexed      BOOLEAN DEFAULT FALSE,
    last_indexed_at TIMESTAMP WITH TIME ZONE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT unique_tenant_page UNIQUE (tenant_id, wp_post_id)
);

CREATE INDEX idx_content_pages_tenant ON content_pages(tenant_id);
```

### `indexing_jobs` — Bulk indexing job tracking

**Owned by:** Python backend

Tracks progress of bulk indexing operations. Created when `POST /api/index/bulk` is called, updated as pages are processed, polled via `GET /api/index/status/{job_id}`.

```sql
CREATE TABLE indexing_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
                    -- queued, processing, completed, failed
    total_pages     INTEGER DEFAULT 0,
    pages_indexed   INTEGER DEFAULT 0,
    pages_skipped   INTEGER DEFAULT 0,
    pages_failed    INTEGER DEFAULT 0,
    errors          JSONB DEFAULT '[]',
    started_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at    TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_indexing_jobs_tenant ON indexing_jobs(tenant_id);
CREATE INDEX idx_indexing_jobs_status ON indexing_jobs(status);
```

### `api_usage_logs` — OpenAI API cost tracking

**Owned by:** Python backend

Logs every OpenAI API call for cost monitoring. Helps track actual expenses per tenant and per operation type.

```sql
CREATE TABLE api_usage_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    operation       VARCHAR(30) NOT NULL,
                    -- index_generate, index_embed, search_embed
    model           VARCHAR(50) NOT NULL,
                    -- gpt-4o-mini, text-embedding-3-small
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        DECIMAL(10, 6),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_api_usage_tenant ON api_usage_logs(tenant_id);
CREATE INDEX idx_api_usage_created ON api_usage_logs(created_at);
```

---

## 2. PostgreSQL Tables (Read-only Reference)

### `tenants` — Tenant validation

**Owned by:** Next.js backend
**Python access:** READ-ONLY (for API key validation and tenant status check)

Python only uses these columns:

| Column | Purpose |
|--------|---------|
| `id` | Tenant UUID — used to filter `content_pages` and Pinecone namespaces |
| `status` | Check if tenant is `active` before processing requests |
| `api_key_hash` | Validate incoming `X-API-Key` header |
| `site_domain` | Identify tenant by domain |

```sql
-- Full table owned by Next.js. Python reads only:
SELECT id, status, api_key_hash, site_domain
FROM tenants
WHERE api_key_hash = $1 AND status = 'active';
```

---

## 3. Entity Relationships

```
tenants (read-only, owned by Next.js)
    │
    ├──── (N) content_pages      (Python-owned)
    ├──── (N) indexing_jobs       (Python-owned)
    └──── (N) api_usage_logs     (Python-owned)
```

---

## 4. Pinecone (Vector Database)

### Index Configuration

```
Index Name:  heroiq-search
Metric:      cosine
Dimensions:  1536 (OpenAI text-embedding-3-small)
Cloud:       AWS
Region:      us-east-1
```

### Namespace Strategy

One namespace per tenant — complete data isolation:

```
tenant_a1b2c3d4-e5f6-7890-abcd-ef1234567890   → Tenant A
tenant_f9e8d7c6-b5a4-3210-fedc-ba0987654321   → Tenant B
```

### Vector Record

Search card data (`display_title`, `summary`, `recommended_cta`) is stored **inside Pinecone metadata** — this is how search returns full cards in a single call without needing a separate database lookup.

```json
{
    "id": "page_42_chunk_0",
    "values": [0.023, -0.041, ..., 0.018],
    "metadata": {
        "wp_post_id": 42,
        "page_title": "Root Canal Treatment",
        "page_url": "/services/root-canal-treatment",
        "post_type": "page",
        "chunk_index": 0,
        "chunk_text": "Expert root canal therapy with minimal discomfort...",
        "content_hash": "a1b2c3d4...",
        "display_title": "Root Canal Treatment",
        "summary": "Expert root canal therapy with minimal discomfort using the latest dental technology.",
        "recommended_cta": "Book a Consultation"
    }
}
```

**Vector ID format:** `page_{wp_post_id}_chunk_{chunk_index}` — deterministic, enables upserts.

### Chunking Parameters

| Parameter | Value |
|-----------|-------|
| Chunk size | 500 tokens |
| Overlap | 50 tokens |
| Min chunk size | 50 tokens (skip tiny chunks) |

---

## 5. Database Ownership Summary

| Table | Owner | Python Access |
|-------|-------|---------------|
| `tenants` | Next.js | Read-only |
| `tenant_config` | Next.js | None |
| `tenant_buttons` | Next.js | None |
| `subscriptions` | Next.js | None |
| `credits` | Next.js | None |
| `credit_transactions` | Next.js | None |
| `sync_schedules` | Next.js | None |
| `search_queries` | Next.js | None |
| `button_clicks` | Next.js | None |
| `leads` | Next.js | None |
| `admin_users` | Next.js | None |
| **`content_pages`** | **Python** | **Read/Write** |
| **`indexing_jobs`** | **Python** | **Read/Write** |
| **`api_usage_logs`** | **Python** | **Read/Write** |
