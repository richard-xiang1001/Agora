from __future__ import annotations

import sys
import time
import unittest
from unittest.mock import patch

from agora.debate_executor import DebateExecutor, DebateRoundTimeoutError
from agora.llm_client import LLMClient, LlmPolicy
from agora.prompt_registry import load_catalog
from scripts import run_debate


class _SlowLLMClient(LLMClient):
    @property
    def source(self) -> str:
        return "mock:slow"

    def generate_claim(self, diff: str, system_prompt: str, agent_id: str) -> dict[str, object]:
        _ = (diff, system_prompt, agent_id)
        time.sleep(3)
        return {
            "agent_id": agent_id,
            "task_intent": "code_review",
            "risk_level": "low",
            "reversibility": "reversible",
            "tool_need": False,
            "conclusion": "slow response",
            "evidence": ["n/a"],
            "assumptions": ["n/a"],
            "confidence": "low",
        }


class DebateExecutorTimeoutTests(unittest.TestCase):
    def test_executor_round_timeout_raises(self) -> None:
        registry = load_catalog("config/prompt_catalog.yaml")
        binding = registry.resolve_profile("profile.debate_code_review")
        policy = LlmPolicy(
            schema_version="1.0",
            provider="openrouter",
            mode="openrouter",
            model="qwen/qwen3-4b:free",
            timeout_seconds=1,
            max_retries=0,
            retry_on=[],
            fallback_on_error=False,
        )
        executor = DebateExecutor(prompt_root_dir=".", llm_policy=policy)

        with self.assertRaisesRegex(DebateRoundTimeoutError, "round1 timeout"):
            executor.run(
                diff="fix: remove unused import",
                routing_features={
                    "task_intent": "code_review",
                    "risk_level": "medium",
                    "reversibility": "partial",
                    "requires_tools": False,
                    "confidence": 0.9,
                },
                binding=binding,
                llm_client=_SlowLLMClient(),
                use_mock=False,
            )

    def test_run_debate_returns_code_3_on_round_timeout(self) -> None:
        argv = ["run_debate.py", "--diff", "fix: noop", "--mock"]
        with patch.object(sys, "argv", argv), patch.object(
            run_debate.DebateExecutor,
            "run",
            side_effect=DebateRoundTimeoutError("round2 timeout after 2s"),
        ):
            rc = run_debate.main()
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
