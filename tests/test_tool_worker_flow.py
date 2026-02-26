from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agora.execution_controller import ExecutionController
from agora.irreversibility_gate import IrreversibilityGate
from agora.models import ToolActionRequest
from agora.tool_worker import ToolWorker


class ToolWorkerFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = ToolWorker(ExecutionController("config/permissions_scopes.yaml"), IrreversibilityGate())

    def test_allowed_action_executes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "foo.txt"
            p.write_text("hello", encoding="utf-8")
            action = ToolActionRequest(
                workflow_id="wf-1",
                action_id="act-1",
                action="read_session_file",
                risk_level="low",
                reversible=True,
                idempotent=True,
                payload={"path": "foo.txt"},
            )
            r = self.worker.execute("scope_unknown_intersection", action, root)
            self.assertEqual(r.status, "allowed")
            self.assertEqual(r.output, "hello")

    def test_denied_action_rejected(self) -> None:
        action = ToolActionRequest(
            workflow_id="wf-1",
            action_id="act-2",
            action="external_write_api",
            risk_level="low",
            reversible=True,
            idempotent=True,
            payload={},
        )
        r = self.worker.execute("scope_unknown_intersection", action, ".")
        self.assertEqual(r.status, "rejected")

    def test_high_irreversible_pending(self) -> None:
        action = ToolActionRequest(
            workflow_id="wf-1",
            action_id="act-3",
            action="write_decision_draft",
            risk_level="high",
            reversible=False,
            idempotent=False,
            payload={"content": "x"},
        )
        r = self.worker.execute("scope_unknown_intersection", action, ".")
        self.assertEqual(r.status, "pending_approval")


if __name__ == "__main__":
    unittest.main()
