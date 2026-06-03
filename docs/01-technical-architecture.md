# HeroIQ Python Backend — Technical Architecture

**Stack:** Python 3.11 | FastAPI | PostgreSQL (shared, managed) | Pinecone | OpenAI
**Host:** DigitalOcean App Platform — `hammerhead-app` (NYC1, Basic plan: 1 vCPU / 1 GB RAM, single always-on instance, $12/mo)
**Production URL:** `https://hammerhead-app-f9fjz.ondigitalocean.app`
**Planned custom domain:** `ai.heroiq.io` (DNS not yet configured)

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
                 │  POST /api/index            (single-page upsert)
                 │  POST /api/search
                 │  DELETE /api/index/*
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│  DigitalOcean App Platform                       │
│  (managed edge router — HTTPS termination,       │
│   certificate provisioning, routing)             │
│  → forwards to container port 8000               │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│  Container (Dockerfile: python:3.11-slim)        │
│  CMD: gunicorn app.main:app -c gunicorn.conf.py  │
│                                                  │
│  Gunicorn (4 UvicornWorker workers, 120s         │
│  timeout, bind 0.0.0.0:$PORT)                    │
│  ┌────────────────────────────────────────────┐  │
│  │            FastAPI Application             │  │
│  │  CORS allow_origins=["*"]                  │  │
│  │  Sentry (conditional on SENTRY_DSN)        │  │
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
┌─────────────┐ ┌──────────────────────────────┐
│ PostgreSQL  │ │      External Services       │
│ (DO Managed │ │  ┌──────────┐ ┌──────────┐  │
│  cluster,   │ │  │ Pinecone │ │  OpenAI  │  │
│  shared)    │ │  │(Vectors) │ │(LLM+Emb)│  │
│             │ │  └──────────┘ └──────────┘  │
│ 3 tables    │ │                              │
│ (Python)    │ │                              │
└─────────────┘ └──────────────────────────────┘
```

```
Widget (search) ──→ Next.js (credit check) ──→ Python (POST /api/search)
Next.js (indexing) ──→ Python (POST /api/index/bulk)
```

**Process management:** No supervisor or systemd. Container lifecycle is managed by DigitalOcean App Platform — the Docker `CMD gunicorn app.main:app -c gunicorn.conf.py` starts 4 Gunicorn workers, and App Platform restarts the container on crash.

**No reverse proxy in the app:** DO App Platform's built-in edge router handles HTTPS termination, certificate provisioning (managed automatically), and routing. There is no nginx, traefik, or other reverse-proxy configuration in the codebase.

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
2. Generate query embedding (~50ms ideal, 300-700ms typical in prod)
   text-embedding-3-small → [1536 floats]
       │
       ▼
3. Pinecone vector search (~100-300ms)
   namespace: tenant_{uuid}, top_k=5
       │
       ▼
4. Deduplicate by page_id → top 3 unique pages
       │
       ▼
5. Return full search cards from Pinecone metadata:
   → display_title, summary, recommended_cta, page_url, score, matched_chunk
```

**Ideal response time:** 200-350ms (Pinecone + OpenAI under no load).
**Real-world production latency:** ~800-2400ms end-to-end, dominated by OpenAI embedding call (300-700ms) + Pinecone query (100-300ms) + network. See CLAUDE.md May-7 notes for the measurements.

**No credit check in Python** — Next.js handles credit verification before calling Python.

**Why no LLM at query time?**

| Approach | Per-query cost | Response time | 100K queries/month |
|----------|---------------|---------------|--------------------|
| Full RAG (LLM every query) | $0.003-0.01 | 1-3s | $300-1,000 |
| **This approach** (pre-built cards) | $0.0001 | 200-350ms ideal | $10-30 |

---

## Multi-Tenancy

Every client is identified by `tenant_id` (Prisma string ID, not Postgres UUID). Isolation at every layer:

| Layer | Method |
|-------|--------|
| API | API key validated → `tenant_id` extracted; all queries filter by it |
| PostgreSQL | `content_pages`, `indexing_jobs`, `api_usage_logs` all have `tenant_id` column (indexed) |
| Pinecone | One namespace per tenant: `tenant_{uuid}` |

---

## Authentication

### Next.js → Python (service-to-service)
- API key passed via `X-API-Key` header.
- Python validates it against `Tenant.serialKey` (Prisma column, camelCase in DB) using **plaintext** comparison — see `app/api/deps.py:17-40`. The exact same plaintext key is what the WordPress plugin pastes during onboarding and what Next.js validates in `/api/plugin/config?key=...`.
- Tenant `status` must be `ACTIVE` (Postgres enum `TenantStatus`: PENDING / ACTIVE / PAST_DUE / EXPIRED).
- All endpoints (except `/api/health`) require a valid API key.

```
X-API-Key: <64-hex-char serial key, or legacy HIQ-XXXXXX-XXXXXX>
Content-Type: application/json
```

> Hashed-key auth (e.g. an `api_key_hash` column) is on the roadmap but **not implemented**. Keys are compared as plaintext today. If hashing is added later, the Prisma schema in `heroiq-super-admin/` must be migrated alongside this backend.

---

## Background Tasks (FastAPI BackgroundTasks)

| Task | Trigger | Action |
|------|---------|--------|
| Bulk content indexing | `POST /api/index/bulk` | Process all pages in background, track progress in `indexing_jobs` table |

No Celery, Redis, RabbitMQ, or external queue. FastAPI's built-in `BackgroundTasks` handles bulk indexing. Job progress is tracked in the `indexing_jobs` PostgreSQL table.

---

## Rate Limiting

**Not currently enforced in code.** There is no rate-limit middleware in `app/main.py`, and SlowAPI (or any equivalent) is not in `requirements.txt`. Per-IP rate limiting that existed earlier was removed in commit `8a14fe2`.

Tenant-level rate limits (e.g. 60 req/min for search, 10 req/min for indexing) are documented as future enhancements in `03-api-endpoints.md`, but no enforcement runs today. Upstream rate limits from OpenAI and Pinecone apply naturally.

---

## Security

- HTTPS enforced by DigitalOcean App Platform (managed certificates, automatic renewal — no Let's Encrypt to configure).
- API key validation (plaintext comparison) on all protected endpoints — `app/api/deps.py:17-40`.
- Pydantic models for input validation on every request body (`app/schemas/*`).
- SQLAlchemy ORM — parameterized queries only, no raw string SQL.
- CORS currently permissive (`allow_origins=["*"]` in `app/main.py:31`). Tighten to the Next.js origin before treating this as production-hardened.

---

## Error Handling

| Scenario | Fallback |
|----------|----------|
| OpenAI API down | Return error: "Indexing temporarily unavailable" |
| Pinecone API down | Return error: "Search temporarily unavailable" |
| LLM response slow (>3s) | Timeout, skip search card generation, use raw title/content |
| Content sync fails | Keep existing index, log error, return error in job status |
| Bulk indexing job fails | Mark job as `failed`, return errors in status endpoint |

Exception handlers registered via `register_exception_handlers(app)` from `app/core/exceptions.py`. Custom `HeroIQException` / `ServiceUnavailableError` types return uniform JSON error bodies.

---

## Deployment

```
DigitalOcean App Platform (managed PaaS, NYC1)
└── Web service: hammerhead-app (Basic plan, $12/mo)
    ├── Container: python:3.11-slim, CMD gunicorn app.main:app -c gunicorn.conf.py
    ├── Gunicorn: 4 UvicornWorker workers, 120s timeout, bind 0.0.0.0:$PORT
    ├── FastAPI app: /api routes mounted, CORS open
    ├── PostgreSQL: shared DigitalOcean Managed cluster (cluster `heroiq-prod-db`)
    │                Python uses database `heroiq_ai`; Next.js uses `heroiq_app`.
    │                Both live inside the same cluster, separate databases.
    └── External: Pinecone, OpenAI
```

The container is the only runtime. There is no OS-level process supervisor, no separate worker pool, no scheduled jobs (cron) inside this service. Health-check probes are configured on the App Platform side to hit `GET /api/health`.

---

## Monitoring

- **Logs:** Gunicorn writes access and error logs to stdout (`accesslog="-"`, `errorlog="-"` in `gunicorn.conf.py`). DigitalOcean App Platform captures them and provides retention + search in its dashboard. No log rotation is configured (or needed) inside the container.
- **Errors:** Sentry — initialized conditionally in `app/main.py:14-16` only if `SENTRY_DSN` env var is set. `traces_sample_rate=0.1` (10% of traces sampled). FastAPI integration auto-captures unhandled exceptions.
- **Uptime:** Not configured in this repo. The legacy reference to UptimeRobot / BetterStack is aspirational — wire it up externally if needed.
- **Metrics:** No metric pipeline configured here. Indexing throughput, search response times, OpenAI/Pinecone API latency, and error rates can be derived from `api_usage_logs` table + Sentry traces.
- **Alerts:** Not configured in this repo. DigitalOcean App Platform offers alerting on CPU / memory / restart count from its dashboard.
