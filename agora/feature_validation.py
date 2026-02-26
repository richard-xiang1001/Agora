from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agora.models import FALLBACK_FEATURES, TaskFeatures


def validate_task_features(raw: dict[str, Any]) -> tuple[TaskFeatures, str]:
    """Validate raw extractor payload; degrade to unknown on any schema failure."""

    try:
        return TaskFeatures(**raw), "pass"
    except ValidationError:
        return FALLBACK_FEATURES, "degraded_to_unknown"
