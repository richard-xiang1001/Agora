from __future__ import annotations

import unittest

from workflows.final_decision import FinalDecision


class FinalDecisionTests(unittest.TestCase):
    def test_suspend_requires_fields(self) -> None:
        with self.assertRaises(ValueError):
            FinalDecision(
                status="SUSPEND_DECISION",
                final_answer="",
                evidence_sources=["agent_a"],
                confidence_label="low",
                core_assumptions=["assumption"],
                uncertainties=["uncertain"],
                evidence_independence_check=False,
                verification_outcome="uncertain",
            )

    def test_final_allows_required_fields(self) -> None:
        d = FinalDecision(
            status="FINAL",
            final_answer="apply parameterized query",
            evidence_sources=["agent_a", "sandbox_poc"],
            confidence_label="high",
            core_assumptions=["db connector uses provided query string"],
            uncertainties=["test fixture DB differs from prod"],
            evidence_independence_check=True,
            verification_outcome="confirmed",
        )
        self.assertEqual(d.status, "FINAL")


if __name__ == "__main__":
    unittest.main()
