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
        self.worker = ToolWorker(
            ExecutionController("config/permissions_scopes.yaml", "config/runtime_capabilities.yaml"),
            IrreversibilityGate(),
            sandbox_spec_path="config/sandbox_spec.yaml",
        )

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
        r = self.worker.execute("scope_code_review", action, ".")
        self.assertEqual(r.status, "pending_approval")

    def test_sandbox_verification_l3_unavailable(self) -> None:
        worker = ToolWorker(
            ExecutionController(
                "config/permissions_scopes.yaml",
                "tests/fixtures/runtime_capabilities_unimplemented.yaml",
            ),
            IrreversibilityGate(),
            sandbox_spec_path="config/sandbox_spec.yaml",
            runtime_capabilities_path="tests/fixtures/runtime_capabilities_unimplemented.yaml",
        )
        action = ToolActionRequest(
            workflow_id="wf-1",
            action_id="act-4",
            action="run_sandbox_verification",
            risk_level="low",
            reversible=True,
            idempotent=True,
            payload={},
        )
        r = worker.execute("scope_code_review", action, ".")
        self.assertEqual(r.status, "rejected")
        self.assertIn("l3_isolation_unavailable", r.reason)


if __name__ == "__main__":
    unittest.main()
