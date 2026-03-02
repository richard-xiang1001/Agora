from __future__ import annotations

import json
import os
import hashlib
import random
import time
from datetime import datetime, timezone
from time import perf_counter
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

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


class LLMClient(ABC):
    @property
    @abstractmethod
    def source(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_claim(self, diff: str, system_prompt: str, agent_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def generate_claim_with_meta(
        self,
        *,
        diff: str,
        system_prompt: str,
        agent_id: str,
        round_name: str | None = None,
        role_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()
        payload = self.generate_claim(diff=diff, system_prompt=system_prompt, agent_id=agent_id)
        meta = {
            "provider": "unknown",
            "model": self.source,
            "agent_id": agent_id,
            "round_name": round_name,
            "role_id": role_id,
            "started_at": started,
            "duration_ms": int((perf_counter() - t0) * 1000),
            "attempts": 1,
            "retry_count": 0,
            "final_status_code": None,
            "error_type": None,
            "outcome": "ok",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
            "cost_alert_exceeded": False,
        }
        return payload, meta


class MockLLMClient(LLMClient):
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir
        self._source = "mock:subagent_claim_approve.json"

    @property
    def source(self) -> str:
        return self._source

    def _pick_fixture(self, diff: str) -> str:
        text = str(diff)
        if "[[MOCK:SUSPEND]]" in text:
            return "subagent_claim_suspend.json"
        if "[[MOCK:REQUEST_CHANGES]]" in text:
            return "subagent_claim_request_changes.json"
        return "subagent_claim_approve.json"

    def generate_claim(self, diff: str, system_prompt: str, agent_id: str) -> dict[str, Any]:
        _ = system_prompt  # Prompt text is intentionally ignored in deterministic mock mode.
        fixture = self._pick_fixture(diff)
        payload = json.loads((self.fixture_dir / fixture).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["agent_id"] = agent_id
        self._source = f"mock:{fixture}"
        return payload

    def generate_claim_with_meta(
        self,
        *,
        diff: str,
        system_prompt: str,
        agent_id: str,
        round_name: str | None = None,
        role_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        started = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()
        payload = self.generate_claim(diff=diff, system_prompt=system_prompt, agent_id=agent_id)
        meta = {
            "provider": "mock",
            "model": self.source,
            "agent_id": agent_id,
            "round_name": round_name,
            "role_id": role_id,
            "started_at": started,
            "duration_ms": int((perf_counter() - t0) * 1000),
            "attempts": 1,
            "retry_count": 0,
            "final_status_code": None,
            "error_type": None,
            "outcome": "ok",
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "estimated_cost_usd": None,
            "cost_alert_exceeded": False,
        }
        return payload, meta


class OpenRouterLLMClient(LLMClient):
    def __init__(self, policy: LlmPolicy, *, model_pricing: dict[str, dict[str, float]] | None = None) -> None:
        self.policy = policy
        self._source = f"openrouter:{policy.model}"
        self.model_pricing = model_pricing or {}

    @property
    def source(self) -> str:
        return self._source

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        s = text.strip()
        try:
            obj = json.loads(s)
            if not isinstance(obj, dict):
                raise LlmPolicyError("OpenRouter response is not a JSON object")
            return obj
        except json.JSONDecodeError:
            start = s.find("{")
            end = s.rfind("}")
            if start < 0 or end <= start:
                raise LlmPolicyError("OpenRouter response does not contain JSON object")
            obj = json.loads(s[start : end + 1])
            if not isinstance(obj, dict):
                raise LlmPolicyError("OpenRouter response is not a JSON object")
            return obj

    def generate_claim(self, diff: str, system_prompt: str, agent_id: str) -> dict[str, Any]:
        payload, _ = self.generate_claim_with_meta(
            diff=diff,
            system_prompt=system_prompt,
            agent_id=agent_id,
            round_name=None,
            role_id=agent_id,
        )
        return payload

    def generate_claim_with_meta(
        self,
        *,
        diff: str,
        system_prompt: str,
        agent_id: str,
        round_name: str | None = None,
        role_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        api_key = load_openrouter_api_key()

        from openai import OpenAI

        headers: dict[str, str] = {}
        referer = os.getenv("OPENROUTER_SITE_URL")
        app_name = os.getenv("OPENROUTER_APP_NAME")
        if referer:
            headers["HTTP-Referer"] = referer
        if app_name:
            headers["X-Title"] = app_name

        client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            default_headers=headers or None,
        )

        prompt = (
            "Review this unified diff and produce one strict json_claim_v1 object only.\n"
            f"Use agent_id=\"{agent_id}\".\n"
            "Diff:\n"
            f"{diff}"
        )

        attempts = 1 + int(self.policy.max_retries)
        started = datetime.now(timezone.utc).isoformat()
        t0 = perf_counter()
        retry_count = 0
        final_status_code: int | None = None
        for i in range(attempts):
            try:
                resp = client.chat.completions.create(
                    model=self.policy.model,
                    max_tokens=700,
                    temperature=0,
                    timeout=float(self.policy.timeout_seconds),
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = resp.choices[0].message.content or "{}"
                payload = self._extract_json_object(content)
                payload["agent_id"] = agent_id
                usage = getattr(resp, "usage", None)
                prompt_tokens = _coerce_usage_token(getattr(usage, "prompt_tokens", None))
                completion_tokens = _coerce_usage_token(getattr(usage, "completion_tokens", None))
                total_tokens = _coerce_usage_token(getattr(usage, "total_tokens", None))
                if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
                    total_tokens = prompt_tokens + completion_tokens
                estimated_cost_usd = _estimate_cost_usd(
                    model=self.policy.model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    pricing=self.model_pricing,
                )
                alert_threshold = self.policy.cost_per_call_alert_usd
                cost_alert_exceeded = (
                    isinstance(alert_threshold, (int, float))
                    and estimated_cost_usd is not None
                    and float(estimated_cost_usd) > float(alert_threshold)
                )
                meta = {
                    "provider": "openrouter",
                    "model": self.policy.model,
                    "agent_id": agent_id,
                    "round_name": round_name,
                    "role_id": role_id,
                    "started_at": started,
                    "duration_ms": int((perf_counter() - t0) * 1000),
                    "attempts": i + 1,
                    "retry_count": retry_count,
                    "final_status_code": final_status_code,
                    "error_type": None,
                    "outcome": "ok",
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": estimated_cost_usd,
                    "cost_alert_exceeded": cost_alert_exceeded,
                }
                return payload, meta
            except Exception as exc:  # noqa: BLE001
                status_code = getattr(exc, "status_code", None)
                final_status_code = status_code if isinstance(status_code, int) else None
                if status_code in {401, 403}:
                    raise LlmAuthError(f"openrouter_auth_failed:{status_code}") from exc
                retryable = status_code in set(self.policy.retry_on)
                if i < attempts - 1 and retryable:
                    delay_s = _retry_delay_seconds(self.policy, retry_count)
                    retry_count += 1
                    time.sleep(delay_s)
                    continue
                raise

        raise LlmPolicyError("unreachable retry loop")


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


def _resolve_mock_fixture_dir(root_dir: Path, repo_root: Path) -> Path:
    local = root_dir / "tests" / "fixtures" / "mock_llm_responses"
    if local.exists():
        return local
    repo = repo_root / "tests" / "fixtures" / "mock_llm_responses"
    if repo.exists():
        return repo
    raise LlmPolicyError("mock fixture directory not found")


def build_llm_client(policy: LlmPolicy, *, root_dir: str | Path, repo_root: str | Path) -> LLMClient:
    root = Path(root_dir).resolve()
    repo = Path(repo_root).resolve()
    if policy.mode == "mock":
        return MockLLMClient(_resolve_mock_fixture_dir(root, repo))
    if policy.mode == "openrouter":
        pricing = load_model_pricing(root / "config" / "model_pricing.yaml")
        if not pricing:
            pricing = load_model_pricing(repo / "config" / "model_pricing.yaml")
        return OpenRouterLLMClient(policy, model_pricing=pricing)
    raise LlmPolicyError(f"unsupported llm mode: {policy.mode}")


def _coerce_usage_token(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _estimate_cost_usd(
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


def _retry_delay_seconds(policy: LlmPolicy, retry_index: int) -> float:
    base = int(policy.retry_backoff.base_delay_ms)
    max_delay = int(policy.retry_backoff.max_delay_ms)
    jitter = float(policy.retry_backoff.jitter_ratio)
    delay_ms = min(max_delay, base * (2 ** max(0, retry_index)))
    jitter_ms = random.uniform(0.0, delay_ms * jitter) if delay_ms > 0 else 0.0
    return (delay_ms + jitter_ms) / 1000.0
