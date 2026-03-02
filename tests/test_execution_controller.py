from __future__ import annotations

import unittest

from agora.execution_controller import ExecutionController


class ExecutionControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctrl = ExecutionController(
            "config/permissions_scopes.yaml", "config/runtime_capabilities.yaml"
        )

    def test_unknown_scope_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            self.ctrl.enforce("scope_not_exists", "read_session_file")

    def test_allowed_operation_passes(self) -> None:
        self.ctrl.enforce("scope_unknown_intersection", "read_session_file")

    def test_denied_operation_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            self.ctrl.enforce("scope_unknown_intersection", "external_write_api")

    def test_unknown_scope_cannot_write_decision_draft(self) -> None:
        with self.assertRaises(PermissionError):
            self.ctrl.enforce("scope_unknown_intersection", "write_decision_draft")

    def test_code_review_scope_can_write_decision_draft(self) -> None:
        self.ctrl.enforce("scope_code_review", "write_decision_draft")

    def test_sandbox_op_blocked_without_l3(self) -> None:
        ctrl = ExecutionController(
            "config/permissions_scopes.yaml",
            "tests/fixtures/runtime_capabilities_unimplemented.yaml",
        )
        with self.assertRaises(PermissionError) as ctx:
            ctrl.enforce("scope_code_review", "run_sandbox_verification")
        self.assertIn("l3_isolation_unavailable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
