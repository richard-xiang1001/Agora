from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class LlmPolicyError(RuntimeError):
    pass


class LlmAuthError(LlmPolicyError):
    pass


class DebatePolicy(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    max_parallel_roles: int = Field(default=3, ge=1, le=6)
    round_timeout_seconds: int | None = Field(default=None, ge=1)
    round2_claim_char_limit: int = Field(default=400, ge=100)
    round2_payload_char_limit: int = Field(default=3500, ge=500)
    round3_payload_char_limit: int = Field(default=5000, ge=500)


class RetryBackoffPolicy(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    base_delay_ms: int = Field(default=200, ge=0)
    max_delay_ms: int = Field(default=2000, ge=0)
    jitter_ratio: float = Field(default=0.2, ge=0.0, le=1.0)


class LlmPolicy(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: Literal["1.0"]
    provider: Literal["openrouter"]
    mode: Literal["mock", "openrouter"]
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    retry_on: list[int] = Field(default_factory=list)
    fallback_on_error: bool = False
    debate: DebatePolicy = Field(default_factory=DebatePolicy)
    retry_backoff: RetryBackoffPolicy = Field(default_factory=RetryBackoffPolicy)
    cost_per_call_alert_usd: float | None = Field(default=None, gt=0.0)


def load_llm_policy(path: str | Path) -> LlmPolicy:
    p = Path(path)
    if not p.exists():
        raise LlmPolicyError(f"llm policy file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise LlmPolicyError(f"llm policy root must be object: {p}")
    try:
        return LlmPolicy(**raw)
    except ValidationError as exc:
        raise LlmPolicyError(f"invalid llm policy: {p}: {exc}") from exc


def load_model_pricing(path: str | Path) -> dict[str, dict[str, float]]:
    p = Path(path)
    if not p.exists():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}
    models = raw.get("models", {})
    if not isinstance(models, dict):
        return {}
    out: dict[str, dict[str, float]] = {}
    for model, row in models.items():
        if not isinstance(model, str) or not isinstance(row, dict):
            continue
        prompt_rate = row.get("per_million_prompt_usd")
        completion_rate = row.get("per_million_completion_usd")
        if isinstance(prompt_rate, (int, float)) and isinstance(completion_rate, (int, float)):
            out[model] = {
                "per_million_prompt_usd": float(prompt_rate),
                "per_million_completion_usd": float(completion_rate),
            }
    return out


def load_openrouter_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise LlmAuthError("OPENROUTER_API_KEY is required")
    if not key.startswith("sk-or-v1-"):
        raise LlmAuthError("OPENROUTER_API_KEY format invalid")
    return key


def openrouter_key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def validate_openrouter_auth(policy: LlmPolicy) -> dict[str, str]:
    if policy.mode != "openrouter":
        return {"mode": policy.mode}
    key = load_openrouter_api_key()
    return {
        "mode": policy.mode,
        "provider": policy.provider,
        "model": policy.model,
        "key_fingerprint": openrouter_key_fingerprint(key),
    }
