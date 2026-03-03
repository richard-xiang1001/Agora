from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from agora.llm.costing import coerce_usage_token, estimate_cost_usd
from agora.llm.policy_loader import LlmAuthError, LlmPolicy, LlmPolicyError, load_openrouter_api_key
from agora.llm.retry_backoff import retry_delay_seconds


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
        _ = system_prompt
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
                prompt_tokens = coerce_usage_token(getattr(usage, "prompt_tokens", None))
                completion_tokens = coerce_usage_token(getattr(usage, "completion_tokens", None))
                total_tokens = coerce_usage_token(getattr(usage, "total_tokens", None))
                if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
                    total_tokens = prompt_tokens + completion_tokens
                estimated_cost_usd = estimate_cost_usd(
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
                    delay_s = retry_delay_seconds(self.policy, retry_count)
                    retry_count += 1
                    time.sleep(delay_s)
                    continue
                raise

        raise LlmPolicyError("unreachable retry loop")
