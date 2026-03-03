from __future__ import annotations

from typing import Any


def should_write_memory(*, confidence: float, event_type: str) -> bool:
    if confidence < 0.6:
        return False
    high_value = {
        "workflow_completed",
        "workflow_failed",
        "initiative_executed",
        "session_budget_exceeded",
        "hard_constraint_reject",
    }
    return event_type in high_value


def choose_layer(*, event_type: str, raw_features: dict[str, Any] | None) -> str:
    if event_type in {"workflow_completed", "workflow_failed"}:
        return "episodic"
    if raw_features and str(raw_features.get("task_intent", "")) in {"planning", "research"}:
        return "procedural"
    return "semantic"
