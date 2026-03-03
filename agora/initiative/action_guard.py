from __future__ import annotations

from typing import Any


def evaluate_initiative(
    *,
    policy: dict[str, Any],
    risk_level: str,
    requires_tools: bool,
    hard_constraint_hit: bool,
    budget_policy_applied: str,
) -> tuple[str, bool]:
    mode = str(policy.get("mode", "suggest_only"))
    if mode in {"suggest_only", "manual_confirm"}:
        return "proposed", False
    if mode != "auto_low_risk":
        return "none", False
    if budget_policy_applied == "block":
        return "blocked", False
    if hard_constraint_hit:
        return "blocked", False
    if requires_tools:
        return "blocked", False
    if str(risk_level).lower().strip() != "low":
        return "blocked", False
    return "executed", True
