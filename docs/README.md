# HeroIQ Python Backend — Docs Index

These docs describe the FastAPI service in this repo (the indexing + search backend). Each file is paired with the code files it depends on — if you change the code, update the corresponding doc here.

**Last verified against code:** 2026-05-26
**Single source of truth:** this `docs/` folder. The earlier duplicate at `production_backend/docs/` has been removed.

| Doc | What it covers | Backing code |
|---|---|---|
| [01-technical-architecture.md](01-technical-architecture.md) | Stack, deployment topology, flows, auth, rate limiting, monitoring | `Dockerfile`, `docker-compose.yml`, `gunicorn.conf.py`, `app/main.py`, `app/api/deps.py` |
| [02-database-schema.md](02-database-schema.md) | The 3 Python-owned tables, the read-only `Tenant` table, Pinecone layout, Alembic | `app/models/*.py`, `app/db/session.py`, `app/db/migrations/`, `app/services/pinecone_service.py` |
| [03-api-endpoints.md](03-api-endpoints.md) | All 7 REST endpoints, request/response shapes, error codes | `app/api/v1/{router,health,search,index}.py`, `app/schemas/` |
| [04-pinecone-cost-breakdown.md](04-pinecone-cost-breakdown.md) | Pinecone pricing model, cost projections | `app/services/pinecone_service.py`, `app/config.py` (PINECONE_*) |
| [05-openai-cost-breakdown.md](05-openai-cost-breakdown.md) | OpenAI pricing model, cost projections | `app/services/openai_pricing.py`, `app/services/embedding_service.py`, `app/services/llm_service.py` |
| [06-scaling-strategy.md](06-scaling-strategy.md) | Vertical vs horizontal scaling, App Platform instance count, capacity planning | DigitalOcean App Platform settings (external) |
| [architecture-diagram.html](architecture-diagram.html) | Standalone HTML diagram, open in browser | — |

## What's deliberately NOT in these docs

- **Nginx, Supervisor, Let's Encrypt, Ubuntu Droplet specifics** — none of these are configured. DigitalOcean App Platform manages the container, the HTTPS edge router, and certificate renewal. Older revisions of these docs described a hand-rolled Droplet setup; that infra never shipped.
- **SlowAPI / per-tenant rate limiting** — not implemented in code. The numbers in `03-api-endpoints.md` are design intent only.
- **Hashed API keys (`api_key_hash`)** — not implemented. Auth compares `X-API-Key` plaintext against `Tenant.serialKey` in `app/api/deps.py:17-40`.
- **Celery / Redis / RabbitMQ** — not used. Bulk indexing runs via FastAPI's `BackgroundTasks` and tracks progress in the `indexing_jobs` table.

## How to keep these docs honest

When you change one of the backing code files in the table above, open the matching doc and reconcile any drift. If you discover a doc claim that no longer matches the code, fix the doc (or fix the code, whichever is the intended source of truth) — don't leave the mismatch in place. The discrepancy audit that produced this README was painful; let's not repeat it.
