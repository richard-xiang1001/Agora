from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from agora.debate_executor import DebateExecutor, DebateRoundTimeoutError
from agora.llm_client import LlmAuthError, build_llm_client, load_llm_policy
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
        except LlmAuthError as exc:
            self.fail(f"auth failure should not be skipped: {exc}")
        except DebateRoundTimeoutError as exc:
            self.skipTest(f"debate round timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            status_code = getattr(exc, "status_code", None)
            if status_code in {401, 403}:
                self.fail(f"auth status should fail test: {exc.__class__.__name__}: {exc}")
            if status_code in {404, 429, 500, 502, 503, 504}:
                self.skipTest(f"openrouter transient failure: {exc.__class__.__name__}: {exc}")
            if isinstance(exc, (TimeoutError, OSError, ConnectionError)):
                self.skipTest(f"network transient failure: {exc.__class__.__name__}: {exc}")
            raise
        self.assertIn(verdict.decision, {"APPROVE", "REQUEST_CHANGES", "SUSPEND"})
        round3_path = Path(verdict.round3_path)
        self.assertTrue(round3_path.exists())
        round3_content = round3_path.read_text(encoding="utf-8")
        self.assertGreater(len(round3_content.strip()), 50)
        self.assertNotIn("unavailable", round3_content.lower())
        metrics_path = Path(verdict.session_dir) / "debate" / "debate_metrics.json"
        self.assertTrue(metrics_path.exists())
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        self.assertIn("total_calls", metrics)
        self.assertIn("retry_total", metrics)
        self.assertIn("status_code_histogram", metrics)
        if verdict.decision != "SUSPEND":
            self.assertTrue(bool((verdict.recommendation or "").strip()))
            self.assertGreater(len((verdict.recommendation or "").strip()), 20)


if __name__ == "__main__":
    unittest.main()
