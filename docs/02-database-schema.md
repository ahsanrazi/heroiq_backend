# HeroIQ Python Backend — Database Schema

Two storage systems: **PostgreSQL** (shared database, Python owns 3 tables), **Pinecone** (vector embeddings).

> Python backend shares a PostgreSQL cluster with the Next.js backend. Python owns `content_pages`, `indexing_jobs`, and `api_usage_logs`. All other tables (the Prisma-managed `Tenant`, `Config`, billing, leads, analytics, etc.) are owned by Next.js. In production the two services use **separate databases inside the same DigitalOcean Managed cluster** — `heroiq_app` (Next.js) and `heroiq_ai` (Python).

---

## 1. PostgreSQL Tables (Python-owned)

The SQL below shows the *logical* shape of each table. The actual definitions live in the SQLAlchemy models under `app/models/` and are managed by Alembic migrations under `app/db/migrations/`. Column types reflect what the code actually creates.

### `content_pages` — Indexed content tracking

**Owned by:** Python backend
**Model:** `app/models/content_page.py`

Tracks what content has been indexed per tenant. The `content_hash` field enables delta updates — on re-sync, compare hash. If unchanged, skip re-indexing.

```sql
CREATE TABLE content_pages (
    id              VARCHAR PRIMARY KEY,            -- UUID v4 string, generated in Python
    tenant_id       VARCHAR NOT NULL                -- Prisma string ID, FK to "Tenant".id
                    REFERENCES "Tenant"(id) ON DELETE CASCADE,
    wp_post_id      BIGINT NOT NULL,
    page_title      VARCHAR(500) NOT NULL,
    page_url        VARCHAR(500) NOT NULL,
    post_type       VARCHAR(50) DEFAULT 'page',
    content_hash    VARCHAR(64) NOT NULL,           -- SHA-256 for delta updates
    chunk_count     INTEGER DEFAULT 0,
    is_indexed      BOOLEAN DEFAULT FALSE,
    last_indexed_at TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT unique_tenant_page UNIQUE (tenant_id, wp_post_id)
);

CREATE INDEX idx_content_pages_tenant ON content_pages(tenant_id);
```

> **Note on types:** `id` and `tenant_id` are stored as `VARCHAR` (string), not `UUID`. Prisma in `heroiq-super-admin/` uses string primary keys for the `Tenant` table, so the Python side mirrors that. The `id` happens to be a UUID v4 generated in Python, but the column type is plain string.

### `indexing_jobs` — Bulk indexing job tracking

**Owned by:** Python backend
**Model:** `app/models/indexing_job.py`

Tracks progress of bulk indexing operations. Created when `POST /api/index/bulk` is called, updated as pages are processed, polled via `GET /api/index/status/{job_id}`.

```sql
CREATE TABLE indexing_jobs (
    id              VARCHAR PRIMARY KEY,            -- UUID v4 string
    tenant_id       VARCHAR NOT NULL
                    REFERENCES "Tenant"(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued',
                    -- queued, processing, completed, failed
    total_pages     INTEGER DEFAULT 0,
    pages_indexed   INTEGER DEFAULT 0,
    pages_skipped   INTEGER DEFAULT 0,
    pages_failed    INTEGER DEFAULT 0,
    errors          JSONB DEFAULT '[]',
    started_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP
);

CREATE INDEX idx_indexing_jobs_tenant ON indexing_jobs(tenant_id);
CREATE INDEX idx_indexing_jobs_status ON indexing_jobs(status);
```

### `api_usage_logs` — OpenAI API cost tracking

**Owned by:** Python backend
**Model:** `app/models/api_usage_log.py`

Logs every OpenAI API call for cost monitoring. Helps track actual expenses per tenant and per operation type.

```sql
CREATE TABLE api_usage_logs (
    id              VARCHAR PRIMARY KEY,            -- UUID v4 string
    tenant_id       VARCHAR NOT NULL
                    REFERENCES "Tenant"(id) ON DELETE CASCADE,
    operation       VARCHAR(30) NOT NULL,
                    -- index_generate, index_embed, search_embed
    model           VARCHAR(50) NOT NULL,
                    -- gpt-4o-mini, text-embedding-3-small
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER DEFAULT 0,
    cost_usd        NUMERIC(17, 12),                -- picocent precision
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_api_usage_tenant ON api_usage_logs(tenant_id);
CREATE INDEX idx_api_usage_created ON api_usage_logs(created_at);
```

> **`cost_usd` precision:** the column is `NUMERIC(17, 12)` — 12 decimal places. Originally `DECIMAL(10, 6)`; it was widened twice (to `(14, 9)` then to `(17, 12)`) because tiny OpenAI operations like a 6-token query embed cost ~`$0.00000012`, which truncated to zero at lower precision. Migrations: `20260520120000_widen_cost_usd_precision` and `20260520140000_widen_cost_usd_to_17_12`.

---

## 2. PostgreSQL Tables (Read-only Reference)

### `Tenant` — Tenant validation

**Owned by:** Next.js / Prisma (in `heroiq-super-admin/prisma/schema.prisma`)
**Python access:** READ-ONLY (for API-key validation and tenant status check)
**Model:** `app/models/tenant.py`

The Prisma table is named `Tenant` (PascalCase, quoted in SQL). Columns Python reads:

| Python attribute | DB column | Purpose |
|---|---|---|
| `id` | `id` | Tenant string ID — used to filter `content_pages`, `indexing_jobs`, `api_usage_logs`, and Pinecone namespaces. |
| `serial_key` | `serialKey` | Validate incoming `X-API-Key` header (plaintext comparison). |
| `status` | `status` | Postgres enum `TenantStatus` (values: `PENDING`, `ACTIVE`, `PAST_DUE`, `EXPIRED`). Tenant must be `ACTIVE` to authenticate. |
| `plugin_site_url` | `pluginSiteUrl` | Bound WordPress site URL (informational; not enforced by Python). |

```sql
-- Owned by Prisma. Python performs only this lookup:
SELECT id, "serialKey", status, "pluginSiteUrl"
FROM "Tenant"
WHERE "serialKey" = $1 AND status = 'ACTIVE';
```

> The legacy `api_key_hash` and `site_domain` column names referenced in earlier doc revisions **do not exist**. Auth happens via plaintext `serialKey` comparison. If the team later moves to hashed keys, both the Prisma schema and `app/models/tenant.py` will need migrations.

---

## 3. Entity Relationships

```
Tenant (read-only, owned by Next.js/Prisma)
    │
    ├──── (N) content_pages      (Python-owned, CASCADE on tenant delete)
    ├──── (N) indexing_jobs       (Python-owned, CASCADE on tenant delete)
    └──── (N) api_usage_logs     (Python-owned, CASCADE on tenant delete)
```

When the super-admin deletes a tenant from `/admin/clients/[id]`, the `ON DELETE CASCADE` clauses above remove all Python-owned rows for that tenant automatically. The Pinecone namespace is wiped separately by the `DELETE /api/index/tenant/{tenant_id}` call that the delete handler also fires.

---

## 4. Pinecone (Vector Database)

### Index Configuration

```
Index Name:  heroiq-search       (env: PINECONE_INDEX_NAME)
Metric:      cosine
Dimensions:  1536                 (OpenAI text-embedding-3-small)
Cloud:       AWS                  (configured in Pinecone dashboard, not in code)
Region:      us-east-1            (configured in Pinecone dashboard, not in code)
```

The cloud/region selection is not represented in this repo — only the index name is read from env (`PINECONE_INDEX_NAME`, defaults to `heroiq-search`). The Pinecone account and index must be provisioned in the Pinecone console with the correct configuration before the service can run.

### Namespace Strategy

One namespace per tenant — complete data isolation:

```
tenant_clt1xyz0abc...   → Tenant A
tenant_clt2def4ghi...   → Tenant B
```

(The IDs above are Prisma cuid/string IDs, not Postgres UUIDs.)

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

| Parameter | Env var | Default |
|-----------|---------|---------|
| Chunk size | `CHUNK_SIZE` | 500 tokens |
| Overlap | `CHUNK_OVERLAP` | 50 tokens |
| Min chunk size | `MIN_CHUNK_SIZE` | 50 tokens (skip tiny chunks) |

All three are read from `app/config.py` and can be overridden via environment variables.

---

## 5. Database Ownership Summary

| Table | Owner | Python Access |
|-------|-------|---------------|
| `Tenant` | Next.js / Prisma | Read-only (auth lookup) |
| `Config`, `Button`, `Lead`, `Subscription`, `CreditTransaction`, `SearchClick`, `User`, `ApiUsageLog` (Prisma's own analytics), etc. | Next.js / Prisma | None |
| **`content_pages`** | **Python** | **Read/Write** |
| **`indexing_jobs`** | **Python** | **Read/Write** |
| **`api_usage_logs`** | **Python** | **Read/Write** |

> The Prisma side has its own `ApiUsageLog` table (for Next.js-recorded API hits). The Python side's `api_usage_logs` (snake_case) is a separate table living in the `heroiq_ai` database, used only for OpenAI cost tracking. Names are similar but the two tables are independent.

---

## 6. Migrations

Schema changes on the Python side are managed by **Alembic** (`app/db/migrations/`). Configuration in `alembic.ini`. To create a new migration:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

Migrations run automatically on deploy via the App Platform build/run command pipeline. **Do not run Alembic against the `heroiq_app` database** — that database belongs to the Next.js Prisma schema and any Alembic activity there will conflict with Prisma's migration history.
