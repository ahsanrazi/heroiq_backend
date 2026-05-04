# HeroIQ Python Backend — Technical Architecture

**Stack:** Python 3.11+ | FastAPI | PostgreSQL 15 (shared) | Pinecone | OpenAI
**Host:** DigitalOcean SFO3 (Ubuntu 22.04, 2-4GB RAM)
**Domain:** `ai.heroiq.io`

> Python backend handles **only** search and content indexing. All business logic (billing, leads, config, analytics, admin) lives in the Next.js backend.

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     Next.js Backend                          │
│         (billing, config, leads, analytics, admin)           │
│                    api.heroiq.io                             │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 │  POST /api/index/bulk
                 │  POST /api/index
                 │  DELETE /api/index/*
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│  Nginx (Reverse Proxy + SSL via Let's Encrypt)   │
│  ai.heroiq.io → localhost:8000                   │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  Gunicorn (4 workers)                            │
│  ┌────────────────────────────────────────────┐  │
│  │            FastAPI Application             │  │
│  │                                            │  │
│  │  ┌────────────┐  ┌───────────────────────┐ │  │
│  │  │ Search API │  │ Index API             │ │  │
│  │  │            │  │ (single + bulk + del) │ │  │
│  │  └────────────┘  └───────────────────────┘ │  │
│  └────────────────────────────────────────────┘  │
└──────────┬──────────┬────────────────────────────┘
           │          │
     ┌─────┘    ┌─────┘
     ▼          ▼
┌─────────┐ ┌──────────────────────────────┐
│PostgreSQL│ │      External Services       │
│ (shared) │ │  ┌──────────┐ ┌──────────┐  │
│          │ │  │ Pinecone │ │  OpenAI  │  │
│ 2 tables │ │  │(Vectors) │ │(LLM+Emb)│  │
│ (Python) │ │  └──────────┘ └──────────┘  │
└─────────┘ └──────────────────────────────┘
```

```
Widget (search) ──→ Next.js (credit check) ──→ Python (POST /api/search)
Next.js (indexing) ──→ Python (POST /api/index/bulk)
```

**Process Manager:** Supervisor (manages Gunicorn)

---

## Core Flow 1: Content Indexing (LLM runs here)

The LLM (GPT-4o-mini) is called **once per page** during indexing — this is the only place LLM is used.

### Single Page Index

```
Next.js Backend → POST /api/index
       │
       ▼
1. Validate API key → extract tenant_id
       │
       ▼
2. Hash content (SHA-256) → compare with stored hash
   → If unchanged → skip, return existing card
       │
       ▼
3. Chunk content (500 tokens, 50 overlap)
       │
       ├──────────────────────────────┐
       ▼                              ▼
4a. Generate embeddings          4b. Generate search card
    (text-embedding-3-small)         (GPT-4o-mini, once per page)
    1536-dim vectors                 → display_title (60 chars)
       │                             → summary (160 chars)
       ▼                             → recommended_cta
5. Store vectors + search card       │
   in Pinecone metadata              │
   namespace: tenant_{uuid}          │
   id: page_{post_id}_chunk_{i}      │
       │                              │
       └──────────────┬───────────────┘
                      ▼
6. Track in PostgreSQL (content_pages table)
                      │
                      ▼
7. Return search card in response
```

### Bulk Index (Background Job)

```
Next.js Backend → POST /api/index/bulk { pages: [...200 pages] }
       │
       ▼
1. Validate API key → extract tenant_id
       │
       ▼
2. Create indexing job → return job_id immediately
       │
       ▼
3. FastAPI BackgroundTasks processes pages one by one:
   For each page:
     → Hash compare (skip if unchanged)
     → Chunk → Embed → Generate search card
     → Upsert to Pinecone
     → Update content_pages table
     → Update job progress
       │
       ▼
4. Next.js polls GET /api/index/status/{job_id} for progress
```

**Delta updates:** Content is hashed (SHA-256) per page. Backend compares with stored hash in `content_pages` table — only re-processes changed pages.

**Deletion detection:** Pages in `content_pages` that are NOT in the incoming list are detected as deleted → vectors removed from Pinecone → rows removed from `content_pages`.

**Cost:** 50 pages = ~$0.05 total

---

## Core Flow 2: Search Query (NO LLM)

```
Next.js Backend → POST /api/search { "query": "...", "limit": 3 }
       │
       ▼
1. Validate API key → extract tenant_id
       │
       ▼
2. Generate query embedding (~50ms)
   text-embedding-3-small → [1536 floats]
       │
       ▼
3. Pinecone vector search (~100-200ms)
   namespace: tenant_{uuid}, top_k=5
       │
       ▼
4. Deduplicate by page_id → top 3 unique pages
       │
       ▼
5. Return full search cards from Pinecone metadata:
   → display_title, summary, recommended_cta, page_url, score
```

**Total response time:** 200-350ms

**No credit check in Python** — Next.js handles credit verification before calling Python.

**Why no LLM at query time?**

| Approach | Per-query cost | Response time | 100K queries/month |
|----------|---------------|---------------|--------------------|
| Full RAG (LLM every query) | $0.003-0.01 | 1-3s | $300-1,000 |
| **This approach** (pre-built cards) | $0.0001 | 200-350ms | $10-30 |

---

## Multi-Tenancy

Every client is identified by `tenant_id` (UUID). Isolation at every layer:

| Layer | Method |
|-------|--------|
| API | API key validated → `tenant_id` extracted; all queries filter by it |
| PostgreSQL | `content_pages` has `tenant_id` column (indexed) |
| Pinecone | One namespace per tenant: `tenant_{uuid}` |

---

## Authentication

### Next.js → Python (service-to-service)
- API key via `X-API-Key` header
- Python validates by looking up `api_key_hash` in the shared `tenants` table
- All endpoints (except `/api/health`) require valid API key

```
X-API-Key: hiq_live_xxxxxxxxxxxxxxxxxxxx
Content-Type: application/json
```

---

## Background Tasks (FastAPI BackgroundTasks)

| Task | Trigger | Action |
|------|---------|--------|
| Bulk content indexing | `POST /api/index/bulk` | Process all pages in background, track progress in `indexing_jobs` table |

No Celery needed — FastAPI's built-in `BackgroundTasks` handles bulk indexing. Job progress is tracked in the `indexing_jobs` PostgreSQL table.

---

## Rate Limiting

| Endpoint Category | Limit |
|-------------------|-------|
| Search (`/api/search`) | 60 req/min per tenant |
| Indexing (`/api/index/*`) | 10 req/min per tenant |

Rate limiting uses in-memory tracking via SlowAPI (no Redis dependency).

---

## Security

- HTTPS enforced (SSL/TLS via Let's Encrypt)
- API key validation on all protected endpoints
- Pydantic models for input validation
- SQLAlchemy ORM (parameterized queries, no SQL injection)

---

## Error Handling

| Scenario | Fallback |
|----------|----------|
| OpenAI API down | Return error: "Indexing temporarily unavailable" |
| Pinecone API down | Return error: "Search temporarily unavailable" |
| LLM response slow (>3s) | Timeout, skip search card generation, use raw title/content |
| Content sync fails | Keep existing index, log error, return error in job status |
| Bulk indexing job fails | Mark job as `failed`, return errors in status endpoint |

---

## Deployment

```
DigitalOcean Droplet (Ubuntu 22.04 LTS, 2-4GB RAM)
├── Nginx (reverse proxy, SSL via Let's Encrypt)
│   └── ai.heroiq.io → Gunicorn (localhost:8000)
├── Gunicorn (4 workers, running FastAPI)
├── PostgreSQL 15 (shared with Next.js backend)
└── Supervisor (process management for Gunicorn)
```

---

## Monitoring

- **Logs:** Python `logging` → rotated daily
- **Errors:** Sentry (exception tracking)
- **Uptime:** UptimeRobot / BetterStack (API health)
- **Metrics:** Indexing throughput, search response times, OpenAI/Pinecone API latency, error rates
- **Alerts:** Email on critical failures (server down, high error rate, OpenAI/Pinecone outage)
