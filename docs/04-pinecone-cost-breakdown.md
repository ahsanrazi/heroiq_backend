# Pinecone Cost Breakdown

This document explains what Pinecone is, how it charges us, and how much it will cost for one client and for 200-250 clients. It is written in simple language so anyone can read it top to bottom.

Pinecone is the vector database we use to store and search the indexed content of each client's website. Every time a visitor searches on a client site, we ask Pinecone to find the most relevant pages.

> **Where the configuration actually lives:** the Pinecone index name comes from the `PINECONE_INDEX_NAME` environment variable (default `heroiq-search`, see `app/config.py:10`). The cloud (AWS) and region (us-east-1) are **not** in this codebase — they are chosen when the index is created in the Pinecone console. The Pinecone client itself is wired up in `app/services/pinecone_service.py`.

---

## 1. Pinecone Plans

Pinecone offers four plans. Higher plans give more capacity and lower per-unit prices.

| Plan | Monthly Minimum | Storage | Write Units Included | Read Units Included | Indexes | Notes |
|---|---|---|---|---|---|---|
| Starter | $0 (Free) | 2 GB | 2 million / month | 1 million / month | 5 max | For testing only. Community support. |
| Builder | $20 flat | 10 GB | 5 million / month | 2 million / month | 10 per project | Fixed fee. Usage above limits is **blocked**, not billed. |
| **Standard** | **$50 minimum** | **Unlimited** (pay per GB) | **$4 per million** (pay as you go) | **$16 per million** (pay as you go) | 20 per project | Includes SSO, backups, RBAC. **This is the right plan for us.** |
| Enterprise | $500 minimum | Unlimited | $6 per million | $24 per million | Unlimited | 99.95% uptime SLA, private networking. Only worth it at very high scale. |

On the Standard and Enterprise plans, you are charged for what you actually use each month. If your usage is below the minimum, you still pay the minimum.

Storage on Standard and Enterprise is **$0.33 per GB per month**.

---

## 2. What are RU, WU, and Storage?

Pinecone bills three things separately. Here is what each one means.

### Write Units (WU) — what you pay when adding content

A Write Unit is what Pinecone charges when we add or update content in the database.

- **1 WU = 1 KB of data written**
- Minimum **5 WU per write** (even if the data is smaller)

**Example:** When we index a single chunk of webpage content (about 8 KB in size), it costs about 8 Write Units. If we index 1,000 chunks, that is 8,000 WU. At 4 dollar per million, that costs about $0.03.

### Read Units (RU) — what you pay per search query

A Read Unit is what Pinecone charges when someone runs a search on a client's website.

- **1 RU per 1 GB** of the client's data
- Minimum **0.25 RU per query** (even if the client's data is small)

**Example:** A typical client's data is about 48 MB (much less than 1 GB), so each search uses the minimum **0.25 RU**. If that client gets 1,000 searches in a month, that is 250 RU total. At 16 dollars per million, that costs about $0.004.

### Storage — what you pay to keep the data

Storage is the monthly rent for keeping all the indexed content in Pinecone.

- **$0.33 per GB per month**
- A typical client's data takes about 48 MB (0.048 GB)

**Example:** Storing 0.048 GB for one month costs 0.048 × $0.33 = **about 1.6 cents per client per month**.

---

## 3. Cost for 1 Client (2,000 pages)

Here is what one typical client costs us at Pinecone.

### Assumptions

| Item | Value |
|---|---|
| Pages on the client's website | 2,000 |
| Chunks created per page (Pinecone stores these) | 3 |
| Total chunks for this client | 6,000 |
| Size of each chunk in storage | About 8 KB |
| Total storage used by this client | About 48 MB |
| Average searches per month | 1,000 |

### Monthly Cost

| Cost Type | How It Adds Up | Monthly Cost |
|---|---|---|
| Storage | 0.048 GB × $0.33 | **$0.016** |
| Search queries (reads) | 1,000 queries × 0.25 RU = 250 RU × $16 per million | **$0.004** |
| Initial indexing (writes, one time) | 6,000 chunks × 8 WU = 48,000 WU × $4 per million | $0.19 (one time only) |
| Re-indexing changed pages (about 10% per month) | 4,800 WU × $4 per million | **$0.019** |

**Total ongoing Pinecone cost per client: about $0.04 per month**

The initial $0.19 indexing cost is paid only once, when the client first signs up.

---

## 4. Cost for 200 to 250 Clients

Now multiply those numbers by 200 and 250 clients.

### Total Usage

| Item | 200 Clients | 250 Clients |
|---|---|---|
| Total chunks stored | 1.2 million | 1.5 million |
| Total storage | About 9.6 GB | About 12 GB |
| Total searches per month (1,000 per client) | 200,000 | 250,000 |
| Total Read Units per month | 50,000 RU | 62,500 RU |
| Total Write Units per month (10% re-indexing) | 960,000 WU | 1.2 million WU |

### Monthly Pinecone Bill (Actual Usage)

| Cost Type | 200 Clients | 250 Clients |
|---|---|---|
| Storage (× $0.33/GB) | $3.17 | $3.96 |
| Read Units (× $16 per million) | $0.80 | $1.00 |
| Write Units (× $4 per million) | $3.84 | $4.80 |
| **Actual Usage Total** | **$7.81** | **$9.76** |

### What We Actually Get Billed

Pinecone Standard plan has a **50 dollars per month minimum**. Our actual usage at 200-250 clients is only 8 dollars to 10 dollars. So we pay the minimum.

| Client Count | Actual Usage | Pinecone Bill | Per-Client Cost |
|---|---|---|---|
| 200 | $7.81 | **$50.00** (minimum) | $0.25 per client |
| 250 | $9.76 | **$50.00** (minimum) | $0.20 per client |

**This means we have a lot of room to grow before the bill goes up.** We can keep adding clients and the bill stays at $50 until our actual usage crosses that line.

---

## 5. Recommendation

**We should buy the Pinecone Standard plan ($50 per month minimum).**

Here is why:

| Plan | Why Not / Why Yes |
|---|---|
| Starter (Free) | Too small. Only 2 GB storage — we will hit this with around 40 clients. |
| Builder ($20 flat) | Storage capped at 10 GB. Usage above the limit is **blocked**, not billed — this would break the platform for new clients once we hit the cap. |
| **Standard ($50 minimum)** | **Best fit.** Unlimited storage, pay-as-you-go, low per-unit prices. Includes SSO, backups, role-based access. |
| Enterprise ($500 minimum) | Not worth it yet. Only makes sense when actual usage crosses $500 per month, which is far in the future. |

### How Long Will $50 per Month Last?

At 200 clients we use only 8 dollars of Pinecone capacity. The other $42 of the minimum is unused headroom. Based on our per-client cost, here is when we will start paying more than the minimum:

| Client Count | Actual Pinecone Usage | What We Pay |
|---|---|---|
| 200 | $8 | $50 (minimum) |
| 500 | $20 | $50 (minimum) |
| 1,000 | $39 | $50 (minimum) |
| **~1,300** | **~$50** | **$50** (break-even point) |
| 2,000 | $78 | $78 |
| 5,000 | $195 | $195 |

**We can grow from 200 to about 1,300 clients without our Pinecone bill going up at all.**

### Summary 

1. **Plan to buy:** Pinecone Standard, $50 per month minimum.
2. **Per-client cost today:** 0.25 dollars per client per month (at 200 clients), or $0.20 (at 250 clients).
3. **We can scale to ~1,300 clients on the same $50 bill** before paying more.
4. The cost per client gets **cheaper** the more clients we add, because the $50 minimum is spread across more accounts.

---

## Sources

- [Pinecone Official Pricing Page](https://www.pinecone.io/pricing/)
- [Pinecone Documentation — Understanding Cost](https://docs.pinecone.io/guides/manage-cost/understanding-cost)
