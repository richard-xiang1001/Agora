from __future__ import annotations

import unittest

from agora.execution_controller import ExecutionController


class ExecutionControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ctrl = ExecutionController("config/permissions_scopes.yaml")

    def test_unknown_scope_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            self.ctrl.enforce("scope_not_exists", "read_session_file")

    def test_allowed_operation_passes(self) -> None:
        self.ctrl.enforce("scope_unknown_intersection", "read_session_file")

    def test_denied_operation_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            self.ctrl.enforce("scope_unknown_intersection", "external_write_api")


if __name__ == "__main__":
    unittest.main()
