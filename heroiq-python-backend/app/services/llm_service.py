import json
import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

LLM_MODEL = "gpt-4o-mini"

SEARCH_CARD_PROMPT = """You are a search card generator. Given a webpage's title and content, generate a search card with these fields:
- display_title: A concise, compelling title (max 60 characters)
- summary: A clear description of the page content (max 160 characters)
- recommended_cta: A call-to-action button text (e.g., "Learn More", "Book Now", "Get Started")

Respond ONLY with valid JSON, no markdown or explanation:
{"display_title": "...", "summary": "...", "recommended_cta": "..."}"""


async def generate_search_card(title: str, content: str) -> dict:
    """Generate display_title, summary, and recommended_cta using GPT-4o-mini.
    Called ONCE per page during indexing — NOT at query time.
    """
    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SEARCH_CARD_PROMPT},
            {"role": "user", "content": f"Title: {title}\n\nContent: {content[:3000]}"},
        ],
        temperature=0.3,
        max_tokens=200,
        timeout=10,
    )

    raw = response.choices[0].message.content.strip()

    try:
        card = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"LLM returned invalid JSON, using fallback. Raw: {raw}")
        card = {
            "display_title": title[:60],
            "summary": content[:160],
            "recommended_cta": "Learn More",
        }

    return {
        "display_title": card.get("display_title", title[:60]),
        "summary": card.get("summary", content[:160]),
        "recommended_cta": card.get("recommended_cta", "Learn More"),
        "input_tokens": response.usage.prompt_tokens,
        "output_tokens": response.usage.completion_tokens,
    }
