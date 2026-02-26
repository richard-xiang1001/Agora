from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from agora.models import DecisionStatus, VerificationOutcome, WorkflowContext
from agora.verification_engine import VerificationEngine, create_sandbox_manifest, update_sandbox_manifest


class VerificationEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = VerificationEngine(max_retries=2, retry_delay_seconds=2, max_parallel=8)

    def _ctx(self, risk: str = "medium", rounds: int = 0, max_rounds: int = 2) -> WorkflowContext:
        return WorkflowContext(
            risk_level=risk,
            verification_outcome=VerificationOutcome.CONFIRMED,
            hypothesis_rounds=rounds,
            max_hypothesis_rounds=max_rounds,
            semantic_gate_passed=True,
            structural_gate_passed=True,
        )

    def test_confirmed_goes_final(self) -> None:
        d = self.engine.route_outcome(self._ctx(), VerificationOutcome.CONFIRMED, 0, 0)
        self.assertEqual(d.action, "finalize")
        self.assertEqual(d.status, DecisionStatus.FINAL)

    def test_uncertain_high_risk_suspend(self) -> None:
        d = self.engine.route_outcome(self._ctx(risk="high"), VerificationOutcome.UNCERTAIN, 0, 0)
        self.assertEqual(d.status, DecisionStatus.SUSPEND_DECISION)

    def test_uncertain_medium_needs_review(self) -> None:
        d = self.engine.route_outcome(self._ctx(risk="medium"), VerificationOutcome.UNCERTAIN, 0, 0)
        self.assertEqual(d.status, DecisionStatus.NEEDS_REVIEW)

    def test_infra_error_retry(self) -> None:
        d = self.engine.route_outcome(self._ctx(risk="high"), VerificationOutcome.INFRA_ERROR, 1, 0)
        self.assertEqual(d.action, "retry")
        self.assertEqual(d.retry_after_seconds, 2)

    def test_infra_error_exhausted_high_suspend(self) -> None:
        d = self.engine.route_outcome(self._ctx(risk="high"), VerificationOutcome.INFRA_ERROR, 2, 0)
        self.assertEqual(d.status, DecisionStatus.SUSPEND_DECISION)

    def test_new_hypothesis_exceed_limit_suspend(self) -> None:
        d = self.engine.route_outcome(
            self._ctx(risk="high", rounds=2, max_rounds=2),
            VerificationOutcome.NEW_HYPOTHESIS,
            0,
            0,
        )
        self.assertEqual(d.status, DecisionStatus.SUSPEND_DECISION)

    def test_new_hypothesis_triggers_incremental_debate(self) -> None:
        d = self.engine.route_outcome(
            self._ctx(risk="high", rounds=1, max_rounds=2),
            VerificationOutcome.NEW_HYPOTHESIS,
            0,
            0,
        )
        self.assertEqual(d.action, "debate_incremental")
        self.assertIsNone(d.status)

    def test_sandbox_manifest_create_and_update(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as td:
                m = await create_sandbox_manifest(td, "wf-1")
                data = json.loads(Path(m).read_text(encoding="utf-8"))
                self.assertEqual(data["status"], "active")

                await update_sandbox_manifest(m, status="completed")
                data2 = json.loads(Path(m).read_text(encoding="utf-8"))
                self.assertEqual(data2["status"], "completed")

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
