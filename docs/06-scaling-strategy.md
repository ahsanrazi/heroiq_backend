# Scaling Strategy

This document explains how we will scale the HeroIQ backend to safely handle 200-250 clients and beyond. It compares the two approaches available to us — vertical scaling and horizontal scaling — including the infrastructure changes required for each, the request capacity each delivers, and when to choose one over the other.

It is written in simple language so any reader can understand the trade-offs and pick the right approach for the current stage of the business.

---

## 1. What "Scaling" Means

"Scaling" means giving the backend more capacity so it can handle more clients and more search traffic without slowing down or crashing.

There are two ways to scale:

- **Vertical scaling (scale up):** Make the existing server **bigger**. More CPU power, more memory, faster network on the same machine.
- **Horizontal scaling (scale out):** Add **more servers** that work together as a team, with a traffic director (load balancer) sending requests to whichever server is free.


Both approaches give us more capacity, but the cost, complexity, and reliability trade-offs are very different.

---

## 2. Where We Are Today

| Item | Current Setup |
|---|---|
| DigitalOcean Plan | Basic |
| Cost | $12 per month |
| CPU | 1 shared vCPU |
| Memory | 1 GB |
| Realistic capacity (search requests per second) | 80-120 per second |
| What we use | A single server running our Python backend |
| Backup server | None — if this one crashes, the platform is down |

This is enough for testing and a small number of clients. At 200-250 clients with normal widget usage, it will work for average load but will struggle during traffic spikes or when several clients trigger a full content sync at the same time.

---

## 3. Vertical Scaling Option

### What changes in DigitalOcean

We upgrade the existing single server to a bigger plan. There is no change to the architecture — we just rent a more powerful machine.

| DigitalOcean Plan | CPU | Memory | Monthly Cost |
|---|---|---|---|
| Basic (current) | 1 vCPU | 1 GB | $12 |
| Professional XS | 2 vCPU | 4 GB | $25 |
| **Professional S** (recommended) | **2 vCPU** | **8 GB** | **$50** |
| Professional M | 4 vCPU | 8 GB | $75 |
| Professional L | 4 vCPU | 16 GB | $150 |

Upgrading is done from the DigitalOcean dashboard. No new infrastructure to set up, no other systems to integrate.

### What additional services we need

Even on the bigger server, we need to add a few support services to make the platform stable and observable. These are not unique to vertical scaling — we need them either way — but for vertical they are the **only** extras required.

| Service | Purpose | Monthly Cost |
|---|---|---|
| Database connection pool bump (PgBouncer, already in our DO Postgres plan) | Allow more simultaneous database connections | $0 |
| External uptime monitoring (e.g., UptimeRobot free tier) | Get an SMS/email alert if the site goes down | $0 |
| Error tracking service (e.g., Sentry free tier) | Capture every crash with full context for debugging | $0 |
| DigitalOcean alerts (CPU, memory, response time) | Get notified before problems become outages | $0 (included) |
| Separate background worker for content syncing (optional, recommended at 500+ clients) | Stops bulk content syncs from slowing down live search | $12 |

### Capacity at each plan tier

These numbers assume we have done the standard code improvements (timeouts, caching, retries). Without those improvements, capacity is roughly half.

| Plan | Sustained Search Requests / Second | Burst Capacity | Supports How Many Clients (Real-World Use) |
|---|---|---|---|
| Basic ($12) | 80-120 | 200 | Up to ~150 clients |
| Professional XS ($25) | 250-350 | 500 | Up to ~500 clients |
| **Professional S ($50)** | **500-800** | **1,200** | **Up to ~1,000 clients** |
| Professional M ($75) | 1,000-1,500 | 2,000 | Up to ~2,000 clients |
| Professional L ($150) | 2,000-3,000 | 4,000 | Up to ~5,000 clients |

### Vertical Scaling — Pros and Cons

**Pros:**
- Simple to set up — change a setting in DigitalOcean, done in 5 minutes
- No new systems to learn or maintain
- Cheapest option per request handled
- No coordination problems between servers
- Easy to roll back (downgrade plan)

**Cons:**
- One server means if it crashes, the entire platform is down until it restarts (usually 1-3 minutes)
- There is a hard ceiling — eventually you cannot buy a bigger single server
- Cannot distribute the load across geographic regions for global speed

---

## 4. Horizontal Scaling Option

### What changes in DigitalOcean

Instead of one bigger server, we run **multiple smaller servers** in parallel. DigitalOcean App Platform routes traffic across whatever instance count is configured on the web service — when `instance_count > 1`, the App Platform edge router automatically distributes incoming requests across all of them (this is the "built-in load balancer" referenced below).

> **Today's state:** the `hammerhead-app` service runs on **instance_count = 1**. The App Platform edge router still terminates HTTPS and proxies to that single instance, but no load balancing is happening — all requests land on the same container. Load balancing activates only after the service is scaled to 2+ instances.

A typical horizontal setup looks like this:

| Setup | Description | Monthly Cost |
|---|---|---|
| 3 × Professional XS ($25 each) | Three identical small servers behind the load balancer | $75 |
| Load balancer (included in DO App Platform) | Routes traffic to whichever server is free | $0 |
| Auto-scaling (built into App Platform) | Adds extra servers automatically during traffic spikes, removes them at quiet times | $0 (you only pay for the servers actually running) |

### What NEW services are required (unique to horizontal scaling)

Because we now have multiple servers, several things that worked fine on one server need a **shared service** that all servers can talk to. This is the main complexity cost of going horizontal.

| New Service | Why It's Needed | Monthly Cost |
|---|---|---|
| **Managed Redis** (DigitalOcean) | Shared memory for search cache and rate limiting. Without this, each server has its own cache, dropping the cache effectiveness by 3 times. | $12-15 |
| **Separate bulk indexer worker** (mandatory for horizontal) | A standalone background server that handles client content syncs. Required because we can't have 3 servers all trying to sync the same client's content at the same time. | $12 |
| **Health monitoring per server** | Alerts when one server is unhealthy so traffic stops being sent to it | $0 (included in DO) |

### Capacity at different instance counts

| Setup | Cost (servers + Redis + worker) | Sustained Search Requests / Second | Burst Capacity | Survives 1 Server Crashing? |
|---|---|---|---|---|
| 2 × $25 + Redis + worker | $74 | 200-300 | 600 | Yes (50% capacity during outage) |
| **3 × $25 + Redis + worker** | **$99** | **300-450** | **900-1,200** | **Yes (66% capacity during outage)** |
| 5 × $25 + Redis + worker | $149 | 500-750 | 1,500-2,000 | Yes (80% capacity) |
| 3 × $50 + Redis + worker | $174 | 600-900 | 1,800-2,400 | Yes |

### Horizontal Scaling — Pros and Cons

**Pros:**
- If one server crashes, the others keep serving — no downtime
- Can scale endlessly by adding more servers
- Auto-scaling can add servers automatically during traffic spikes and remove them at quiet times
- Can eventually deploy servers in different geographic regions (US + Europe + Asia)
- Better for clients with strict uptime requirements (signed SLAs)

**Cons:**
- More moving parts to set up and maintain (Redis, worker, multiple servers)
- Costs more for the same capacity (because of the extra shared services)
- Takes 3-5 days of engineering work to set up correctly
- Requires monitoring multiple servers instead of one
- If Redis goes down, the platform loses cache and rate limiting

---

## 5. Side-by-Side Comparison

| Factor | Vertical (Professional S $50) | Horizontal (3 × $25 + Redis + Worker) |
|---|---|---|
| **Monthly cost** | $50 | $99 |
| **Sustained capacity** | 500-800 requests/second | 300-450 requests/second |
| **Burst capacity** | 1,200 requests/second | 900-1,200 requests/second |
| **Survives a server crash?** | No — platform down 1-3 minutes during restart | Yes — other servers keep serving |
| **New systems to manage** | None | Redis + separate worker |
| **Cost per request handled** | Lower | Higher |
| **Auto-scale during spikes?** | No (manual upgrade) | Yes |
| **Best for** | Cost-efficient growth | Uptime guarantees, large scale |

**Important finding:** At our current scale, vertical actually handles **more requests per second per dollar** than horizontal. Horizontal's advantage is **reliability**, not raw capacity.

---

## 6. Recommendation by Client Count

This is the phased path we should follow as the business grows.

### Stage 1: 0-250 clients — Vertical $50 Plan

| Item | Value |
|---|---|
| DigitalOcean Plan | Professional S ($50/mo) |
| Extra services | Free monitoring tools (UptimeRobot, Sentry, DO alerts) |
| Total monthly cost | $50 |
| Capacity | 500-800 requests/second sustained |
| Headroom over expected load | 5-10× |

This is where we are heading right now. Simple, cheap, plenty of capacity for 200-250 clients.

### Stage 2: 250-500 clients — Vertical $50 + Separate Bulk Worker

| Item | Value |
|---|---|
| DigitalOcean Plan | Professional S ($50/mo) |
| Extra services | Add a separate $12/mo worker for content syncing |
| Total monthly cost | $62 |
| Capacity | 500-800 requests/second sustained, with no slowdown during client content syncs |

The separate worker prevents the situation where one client triggering a full sync slows down search for everyone else.

### Stage 3: 500-1,000 clients — Vertical Upgrade OR Transition to Horizontal

**Option A (still vertical):**

| Item | Value |
|---|---|
| DigitalOcean Plan | Professional M ($75/mo) — 4 CPU, 8 GB |
| Bulk worker | $12 |
| Total monthly cost | $87 |
| Capacity | 1,000-1,500 requests/second |

**Option B (switch to horizontal):** $99/mo, less raw capacity but survives crashes. Choose this if at this point we have any client demanding uptime guarantees.

### Stage 4: 1,000+ clients — Horizontal Becomes Necessary

| Item | Value |
|---|---|
| Setup | 3-5 servers at $25 each + Redis + bulk worker |
| Total monthly cost | $100-160 |
| Capacity | 600-1,000 requests/second sustained, with auto-scale to 2,000+ during peaks |
| Survives server crash | Yes |

At this scale, going down for even 1 minute means losing visible revenue. Horizontal becomes worth the extra complexity.

---

## Summary

| Question | Answer |
|---|---|
| **What should we do now for 200-250 clients?** | Vertical scaling, upgrade to DigitalOcean Professional S at $50/month |
| **When do we add the separate bulk worker?** | At 250-500 clients (adds $12/mo) |
| **When do we switch to horizontal?** | When we cross 1,000 clients OR when we sign our first client with a strict uptime SLA |
| **What will it cost at 250 clients?** | $50/month (DigitalOcean) plus the small Pinecone and OpenAI bills covered in earlier documents |
| **What will it cost at 1,000 clients?** | About $87-100/month depending on whether we stay vertical or switch to horizontal |
| **What will it cost at 3,000+ clients?** | $250-500/month for the full horizontal setup with geographic distribution |

The platform is built to scale from where we are today to several thousand clients without architectural rewrites. The only changes needed at each stage are the ones listed above — bigger plans, adding services as we grow, and switching to horizontal only when uptime requirements demand it.

---

## Sources

- [DigitalOcean App Platform Pricing](https://www.digitalocean.com/pricing/app-platform)
- [DigitalOcean App Platform Documentation](https://docs.digitalocean.com/products/app-platform/)
