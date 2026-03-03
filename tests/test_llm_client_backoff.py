from __future__ import annotations

import os
import types
import unittest
from unittest.mock import patch

from agora.llm_client import LlmPolicy, OpenRouterLLMClient, _retry_delay_seconds


class _RetryableError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status={status_code}")
        self.status_code = status_code


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 20
    total_tokens = 30


class _FakeMessage:
    content = '{"conclusion":"ok","risk_level":"low","reversibility":"reversible","tool_need":false,"evidence":[],"assumptions":[],"confidence":"medium","task_intent":"code_review"}'


class _FakeChoice:
    message = _FakeMessage()


class _FakeResp:
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        self.calls += 1
        if self.calls == 1:
            raise _RetryableError(500)
        return _FakeResp()


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeOpenAIClient:
    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        _ = kwargs
        self.chat = _FakeChat()


class LlmClientBackoffTests(unittest.TestCase):
    def test_retry_delay_sequence(self) -> None:
        policy = LlmPolicy(
            schema_version="1.0",
            provider="openrouter",
            mode="openrouter",
            model="qwen/qwen3-4b:free",
            timeout_seconds=30,
            max_retries=3,
            retry_on=[500],
            fallback_on_error=False,
            retry_backoff={
                "base_delay_ms": 100,
                "max_delay_ms": 500,
                "jitter_ratio": 0.0,
            },
        )
        self.assertEqual(_retry_delay_seconds(policy, 0), 0.1)
        self.assertEqual(_retry_delay_seconds(policy, 1), 0.2)
        self.assertEqual(_retry_delay_seconds(policy, 2), 0.4)
        self.assertEqual(_retry_delay_seconds(policy, 3), 0.5)

    def test_openrouter_client_retries_with_backoff(self) -> None:
        policy = LlmPolicy(
            schema_version="1.0",
            provider="openrouter",
            mode="openrouter",
            model="qwen/qwen3-4b:free",
            timeout_seconds=30,
            max_retries=2,
            retry_on=[500],
            fallback_on_error=False,
            retry_backoff={
                "base_delay_ms": 100,
                "max_delay_ms": 500,
                "jitter_ratio": 0.0,
            },
        )
        client = OpenRouterLLMClient(
            policy,
            model_pricing={"qwen/qwen3-4b:free": {"per_million_prompt_usd": 1.0, "per_million_completion_usd": 2.0}},
        )
        fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAIClient)
        with patch.dict("sys.modules", {"openai": fake_module}), patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-v1-aaaaaaaaaaaaaaaa"},
            clear=False,
        ), patch("agora.llm.provider_openrouter.time.sleep") as sleep_mock:
            payload, meta = client.generate_claim_with_meta(
                diff="diff",
                system_prompt="system",
                agent_id="agent-1",
                round_name="round1",
                role_id="r1",
            )
        self.assertEqual(payload["agent_id"], "agent-1")
        self.assertEqual(meta["retry_count"], 1)
        sleep_mock.assert_called_once()
        self.assertEqual(meta["prompt_tokens"], 10)
        self.assertEqual(meta["completion_tokens"], 20)
        self.assertEqual(meta["total_tokens"], 30)
        self.assertIsInstance(meta["estimated_cost_usd"], float)


if __name__ == "__main__":
    unittest.main()
