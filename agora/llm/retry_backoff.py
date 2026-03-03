from __future__ import annotations

import random

from agora.llm.policy_loader import LlmPolicy


def retry_delay_seconds(policy: LlmPolicy, retry_index: int) -> float:
    base = int(policy.retry_backoff.base_delay_ms)
    max_delay = int(policy.retry_backoff.max_delay_ms)
    jitter = float(policy.retry_backoff.jitter_ratio)
    delay_ms = min(max_delay, base * (2 ** max(0, retry_index)))
    jitter_ms = random.uniform(0.0, delay_ms * jitter) if delay_ms > 0 else 0.0
    return (delay_ms + jitter_ms) / 1000.0
