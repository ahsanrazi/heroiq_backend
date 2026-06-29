OPENAI_PRICING = {
    "gpt-4o-mini":            {"input": 0.00015 / 1000, "output": 0.00060 / 1000},
    # gpt-4o vision (brand-color extraction). Image tokens are billed inside
    # prompt_tokens, so the same input/output rates apply. Verify against current
    # OpenAI pricing if it changes: $2.50/1M input, $10.00/1M output.
    "gpt-4o":                 {"input": 0.00250 / 1000, "output": 0.01000 / 1000},
    "text-embedding-3-small": {"input": 0.00002 / 1000, "output": 0.0},
}


def calc_cost(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    p = OPENAI_PRICING.get(model)
    if not p:
        return 0.0
    return round(input_tokens * p["input"] + output_tokens * p["output"], 12)
