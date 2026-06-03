# OpenAI Cost Breakdown

This document explains what OpenAI is costing HeroIQ, how the billing works, and what it will cost for one client and for 200-250 clients. It is written in simple language so anyone can read it top to bottom.

OpenAI is the AI provider we use for two things:

1. **Reading and understanding each page** on a client's website at indexing time, so we can build a smart search result card for it.
2. **Turning text into numbers (embeddings)** so the search engine can find similar content quickly.

We use two OpenAI models:

- **gpt-4o-mini** — the AI model that reads pages and writes the search result cards
- **text-embedding-3-small** — the model that converts text into numbers for search

---

## 1. OpenAI Billing Model

OpenAI does **not** sell monthly plans like other services. There is no fixed monthly fee and no minimum commitment. You only pay for what you actually use.

### How payment works

- You **pre-pay credits** into your account (for example, $20)
- Every API call deducts a small amount based on tokens used
- When the balance gets low, OpenAI can **auto-recharge** (top up automatically)
- You receive a monthly invoice summarizing all usage

### Current rates for the two models we use (2026)

| Model | What it does | Input price | Output price |
|---|---|---|---|
| gpt-4o-mini | Builds search result cards from page content | $0.15 per million tokens | $0.60 per million tokens |
| text-embedding-3-small | Converts text into numbers for search | $0.02 per million tokens | No output charge |

> The same pricing constants live in code at `app/services/openai_pricing.py`. If OpenAI changes its rates, update that file and the table above together so cost calculations stay consistent.

### A note on usage tiers

OpenAI has 5 usage tiers (Tier 1 to Tier 5). These tiers do **not** change the prices above. They only affect how many requests per minute you can send. New accounts start at Tier 1 and move up automatically after a small amount of spending. We are at Tier 1 today and will move to Tier 2 after $50 of usage.

---

## 2. How Token Billing Works

A **token** is OpenAI's billing unit. One token is roughly **4 characters** of English text, or about **0.75 of a word**. So 1,000 tokens is about 750 words.

**Example:** The sentence "Welcome to our dental clinic" is about 6 tokens.

### Input tokens vs Output tokens

- **Input tokens** = what we send to the AI (a question, a page of content, etc.)
- **Output tokens** = what the AI sends back to us (an answer, a search card, etc.)

The two models we use charge differently:

- **gpt-4o-mini** charges for both input AND output (output is more expensive because the AI did more "thinking")
- **text-embedding-3-small** charges only for input (it doesn't generate text back, just numbers)

### Worked example — gpt-4o-mini

We send a page (about 800 tokens of input). The AI returns a small JSON search card (about 50 tokens of output).

- Input cost: 800 tokens × 0.15 dollars per million = **$0.00012**
- Output cost: 50 tokens × 0.60 dollars per million = **$0.00003**
- Total for one page: **about 0.015 cents**

### Worked example — text-embedding-3-small

A page is broken into 3 chunks of about 500 tokens each = 1,500 tokens total.

- Cost: 1,500 tokens × 0.02 dollars per million = **$0.00003**
- Total for one page: **about 0.003 cents**

---

## 3. Cost for 1 Client (2,000 pages)

Here is what one typical client costs us at OpenAI.

### Assumptions

| Item | Value |
|---|---|
| Pages on the client's website | 2,000 |
| Chunks per page (for embedding) | 3 |
| Average searches per month | 1,000 |
| Average tokens per page (for search card) | 800 input, 50 output |
| Average tokens per chunk (for embedding) | 500 |
| Average tokens per search query | 30 |

### One-Time Indexing Cost (paid once when the client signs up)

| Component | Tokens | Cost |
|---|---|---|
| gpt-4o-mini input (read 2,000 pages) | 1.6 million | $0.24 |
| gpt-4o-mini output (write 2,000 search cards) | 0.1 million | $0.06 |
| text-embedding-3-small (embed 6,000 chunks) | 3 million | $0.06 |
| **Total one-time indexing cost per client** | | **$0.36** |

### Ongoing Monthly Cost (every month after signup)

| Component | Tokens | Cost |
|---|---|---|
| Re-indexing changed pages (about 10% of content per month) — gpt-4o-mini | 170,000 | $0.030 |
| Re-indexing changed pages — embeddings | 300,000 | $0.006 |
| Query embeddings (1,000 searches × 30 tokens) | 30,000 | $0.0006 |
| **Total ongoing cost per client** | | **about $0.04 per month** |

The one-time indexing cost of $0.36 is paid once. After that, the client only costs us about **4 cents per month** at OpenAI.

---

## 4. Cost for 200 to 250 Clients

Now multiply those numbers across our planned scale.

### One-Time Onboarding (paid as clients sign up, not all at once)

| Client Count | One-Time Total |
|---|---|
| 200 | $72 |
| 250 | $90 |

This is spread over weeks or months as new clients onboard, not paid in a single month.

### Ongoing Monthly OpenAI Bill

| Client Count | Ongoing Monthly |
|---|---|
| 200 | about $8 |
| 250 | about $10 |

### Realistic Monthly Bill (ongoing + new client onboarding)

If we are still adding new clients each month, the realistic monthly bill is slightly higher:

| Client Count | Realistic Monthly Bill |
|---|---|
| 200 | 10 dollars to 15 dollars |
| 250 | 12 dollars to 18 dollars |

This includes both the ongoing cost for existing clients AND a few new clients being onboarded that month.

---

## 5. Recommendation

There is no "plan to buy" with OpenAI — it is purely pay-as-you-go. The recommendation is about how to set up the account correctly.

### What we should do

1. **Pre-pay $20 in credits** to start. This covers about 2 to 3 months of usage at the 200-client scale.
2. **Enable auto-recharge** at a 20 dollars trigger. Whenever the balance drops below $20, OpenAI tops it up automatically. This prevents service interruption.
3. **Set a soft monthly budget alert at $50.** This sends an email warning if usage suddenly spikes (for example, if one client uploads an unusually large website). It does not block the service.
4. **Reach Tier 2 quickly.** After $50 of total spending, OpenAI moves us to Tier 2 automatically. Tier 2 gives higher rate limits, which keeps bulk content sync fast when multiple clients onboard at the same time.


### Summary

1. **No plan to buy** — OpenAI is pay-as-you-go.
2. **Pre-pay $20 once, enable auto-recharge.** That is the entire setup.
3. **Per-client cost:** about 0.36 dollars one-time + 0.04 dollars per month.
4. **Monthly bill at 200 clients:** 10 dollars to 15 dollars.
5. **Monthly bill at 250 clients:** 12 dollars to 18 dollars.
6. **OpenAI is the cheapest part of our infrastructure** at this scale — well under our current monthly database costs.

---

## Sources

- [OpenAI API Pricing Page](https://openai.com/api/pricing/)
- [OpenAI Embeddings Documentation](https://platform.openai.com/docs/guides/embeddings)
