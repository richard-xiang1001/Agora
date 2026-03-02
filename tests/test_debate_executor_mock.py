from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agora.debate_executor import DebateExecutor, ROUND1_ROLE_IDS, VERDICT_RE
from agora.llm_client import MockLLMClient
from agora.prompt_registry import load_catalog


class DebateExecutorMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_catalog("config/prompt_catalog.yaml")
        self.binding = self.registry.resolve_profile("profile.debate_code_review")
        self.fixture_dir = Path("tests/fixtures/mock_llm_responses/debate")
        self.executor = DebateExecutor(
            prompt_root_dir=".",
            fixture_root_dir=self.fixture_dir,
        )
        # In mock mode executor does not call llm client, but keep an object for interface parity.
        self.llm_client = MockLLMClient(Path("tests/fixtures/mock_llm_responses"))
        self.routing_features = {
            "task_intent": "code_review",
            "risk_level": "medium",
            "reversibility": "partial",
            "requires_tools": False,
            "confidence": 0.9,
        }

    def test_three_round_mock_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            verdict = self.executor.run(
                diff="fix: remove unused import",
                routing_features=self.routing_features,
                binding=self.binding,
                llm_client=self.llm_client,
                session_dir=Path(td) / "run_basic",
                use_mock=True,
            )
            self.assertIn(verdict.decision, {"APPROVE", "REQUEST_CHANGES", "SUSPEND"})
            self.assertTrue(Path(verdict.round1_path).exists())
            self.assertTrue(Path(verdict.round2_path).exists())
            self.assertTrue(Path(verdict.round3_path).exists())
            for role_id in ROUND1_ROLE_IDS:
                claim_text = (Path(verdict.session_dir) / "claims" / f"{role_id}.md").read_text(encoding="utf-8")
                self.assertIsNotNone(VERDICT_RE.search(claim_text))
            round3 = Path(verdict.round3_path).read_text(encoding="utf-8")
            self.assertNotIn("unavailable", round3.lower())
            if verdict.decision == "SUSPEND":
                self.assertIsNone(verdict.recommendation)
            else:
                self.assertTrue(bool((verdict.recommendation or "").strip()))

    def test_suspend_path_recommendation_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            verdict = self.executor.run(
                diff="[[MOCK:SUSPEND]]\ncritical unsafe change",
                routing_features=self.routing_features,
                binding=self.binding,
                llm_client=self.llm_client,
                session_dir=Path(td) / "run_suspend",
                use_mock=True,
            )
            self.assertEqual(verdict.decision, "SUSPEND")
            self.assertIsNone(verdict.recommendation)
            text = Path(verdict.round3_path).read_text(encoding="utf-8")
            self.assertIn("mode: suspend", text)

    def test_round2_anonymized_payload_has_no_role_labels(self) -> None:
        long = "A" * 1200
        round1_outputs = {rid: f"{long}\nVERDICT: APPROVE from {rid}" for rid in ROUND1_ROLE_IDS}
        payload = self.executor._build_round2_user_input(  # noqa: SLF001
            diff="sample",
            routing_features=self.routing_features,
            role_id="security_reviewer",
            round1_outputs=round1_outputs,
        )
        for rid in ROUND1_ROLE_IDS:
            self.assertNotIn(rid, payload)
        self.assertIn("[TRUNCATED]", payload)


if __name__ == "__main__":
    unittest.main()
