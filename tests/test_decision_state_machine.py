from __future__ import annotations

import unittest

from agora.decision_state_machine import determine_decision_status
from agora.models import DecisionStatus, VerificationOutcome, WorkflowContext


class DecisionStateMachineTests(unittest.TestCase):
    def test_high_risk_uncertain_is_suspend(self) -> None:
        ctx = WorkflowContext(
            risk_level="high",
            verification_outcome=VerificationOutcome.UNCERTAIN,
            hypothesis_rounds=0,
            max_hypothesis_rounds=2,
            semantic_gate_passed=False,
            structural_gate_passed=False,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.SUSPEND_DECISION)

    def test_high_risk_infra_error_is_suspend(self) -> None:
        ctx = WorkflowContext(
            risk_level="high",
            verification_outcome=VerificationOutcome.INFRA_ERROR,
            hypothesis_rounds=0,
            max_hypothesis_rounds=2,
            semantic_gate_passed=True,
            structural_gate_passed=True,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.SUSPEND_DECISION)

    def test_hypothesis_depth_exceeded_is_suspend(self) -> None:
        ctx = WorkflowContext(
            risk_level="high",
            verification_outcome=VerificationOutcome.CONFIRMED,
            hypothesis_rounds=3,
            max_hypothesis_rounds=2,
            semantic_gate_passed=True,
            structural_gate_passed=True,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.SUSPEND_DECISION)

    def test_semantic_fail_is_needs_review(self) -> None:
        ctx = WorkflowContext(
            risk_level="medium",
            verification_outcome=VerificationOutcome.CONFIRMED,
            hypothesis_rounds=0,
            max_hypothesis_rounds=2,
            semantic_gate_passed=False,
            structural_gate_passed=True,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.NEEDS_REVIEW)

    def test_structural_fail_is_needs_review(self) -> None:
        ctx = WorkflowContext(
            risk_level="medium",
            verification_outcome=VerificationOutcome.CONFIRMED,
            hypothesis_rounds=0,
            max_hypothesis_rounds=2,
            semantic_gate_passed=True,
            structural_gate_passed=False,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.NEEDS_REVIEW)

    def test_all_clear_is_final(self) -> None:
        ctx = WorkflowContext(
            risk_level="low",
            verification_outcome=VerificationOutcome.CONFIRMED,
            hypothesis_rounds=0,
            max_hypothesis_rounds=2,
            semantic_gate_passed=True,
            structural_gate_passed=True,
        )
        self.assertEqual(determine_decision_status(ctx), DecisionStatus.FINAL)


if __name__ == "__main__":
    unittest.main()
