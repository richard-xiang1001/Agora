from __future__ import annotations


def coerce_usage_token(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def estimate_cost_usd(
    *,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    pricing: dict[str, dict[str, float]],
) -> float | None:
    if prompt_tokens is None or completion_tokens is None:
        return None
    rates = pricing.get(model)
    if not rates:
        return None
    p_rate = rates.get("per_million_prompt_usd")
    c_rate = rates.get("per_million_completion_usd")
    if not isinstance(p_rate, (int, float)) or not isinstance(c_rate, (int, float)):
        return None
    cost = (prompt_tokens / 1_000_000.0) * float(p_rate) + (completion_tokens / 1_000_000.0) * float(c_rate)
    return round(cost, 8)
