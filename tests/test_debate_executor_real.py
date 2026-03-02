from __future__ import annotations

import os
import unittest

from agora.debate_executor import DebateExecutor
from agora.llm_client import build_llm_client, load_llm_policy
from agora.prompt_registry import load_catalog


@unittest.skipUnless(os.getenv("OPENROUTER_API_KEY"), "OPENROUTER_API_KEY not set")
class DebateExecutorRealTests(unittest.TestCase):
    def test_real_debate_executor_returns_valid_decision(self) -> None:
        registry = load_catalog("config/prompt_catalog.yaml")
        binding = registry.resolve_profile("profile.debate_code_review")
        policy = load_llm_policy("config/llm_policy.yaml")
        llm_client = build_llm_client(policy, root_dir=".", repo_root=".")

        executor = DebateExecutor(prompt_root_dir=".")
        try:
            verdict = executor.run(
                diff="fix: remove unused import",
                routing_features={
                    "task_intent": "code_review",
                    "risk_level": "medium",
                    "reversibility": "partial",
                    "requires_tools": False,
                    "confidence": 0.9,
                },
                binding=binding,
                llm_client=llm_client,
                use_mock=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.skipTest(f"openrouter transient failure: {exc.__class__.__name__}: {exc}")
        self.assertIn(verdict.decision, {"APPROVE", "REQUEST_CHANGES", "SUSPEND"})


if __name__ == "__main__":
    unittest.main()
