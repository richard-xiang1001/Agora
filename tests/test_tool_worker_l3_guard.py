from __future__ import annotations

import unittest

from agora.execution_controller import ExecutionController
from agora.irreversibility_gate import IrreversibilityGate
from agora.models import ToolActionRequest
from agora.tool_worker import ToolWorker


class ToolWorkerL3GuardTests(unittest.TestCase):
    def test_l3_unavailable_blocks_sandbox_verification(self) -> None:
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
            workflow_id="wf-l3",
            action_id="act-l3",
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
