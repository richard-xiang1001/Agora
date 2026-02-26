from __future__ import annotations

import unittest

from agora.irreversibility_gate import IrreversibilityGate
from agora.models import ApprovalState, ToolActionRequest


class IrreversibilityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = IrreversibilityGate()

    def test_high_irreversible_pending(self) -> None:
        action = ToolActionRequest(
            workflow_id="wf-1",
            action_id="act-1",
            action="write_decision_draft",
            risk_level="high",
            reversible=False,
            idempotent=False,
            payload={},
        )
        d = self.gate.require_approval(action)
        self.assertTrue(d.requires_approval)
        self.assertEqual(d.approval_state, ApprovalState.PENDING)

    def test_medium_irreversible_not_required(self) -> None:
        action = ToolActionRequest(
            workflow_id="wf-2",
            action_id="act-2",
            action="write_decision_draft",
            risk_level="medium",
            reversible=False,
            idempotent=False,
            payload={},
        )
        d = self.gate.require_approval(action)
        self.assertFalse(d.requires_approval)
        self.assertIsNone(d.approval_state)


if __name__ == "__main__":
    unittest.main()
