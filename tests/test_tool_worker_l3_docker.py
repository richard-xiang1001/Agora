from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agora.execution_controller import ExecutionController
from agora.irreversibility_gate import IrreversibilityGate
from agora.models import ToolActionRequest
from agora.tool_worker import ToolWorker


class ToolWorkerL3DockerTests(unittest.TestCase):
    def _worker(self) -> ToolWorker:
        return ToolWorker(
            ExecutionController(
                "config/permissions_scopes.yaml",
                "tests/fixtures/runtime_capabilities_docker.yaml",
            ),
            IrreversibilityGate(),
            sandbox_spec_path="config/sandbox_spec.yaml",
            runtime_capabilities_path="tests/fixtures/runtime_capabilities_docker.yaml",
        )

    def _action(self, **payload: object) -> ToolActionRequest:
        return ToolActionRequest(
            workflow_id="wf-docker",
            action_id="act-docker",
            action="run_sandbox_verification",
            risk_level="low",
            reversible=True,
            idempotent=True,
            payload=payload,
        )

    @patch("agora.tool_worker.subprocess.run")
    def test_docker_success_path(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["docker", "compose", "version"], returncode=0, stdout="Docker Compose v2.0\n"
        )
        with tempfile.TemporaryDirectory() as td:
            r = self._worker().execute("scope_code_review", self._action(), Path(td))
        self.assertEqual(r.status, "allowed")
        self.assertTrue(r.output and r.output.endswith("verification_result.json"))

    @patch("agora.tool_worker.subprocess.run")
    def test_docker_failure_fail_closed(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd=["docker", "compose", "version"]
        )
        with tempfile.TemporaryDirectory() as td:
            r = self._worker().execute("scope_code_review", self._action(), Path(td))
        self.assertEqual(r.status, "rejected")
        self.assertIn("sandbox_backend_failed", r.reason)

    @patch("agora.tool_worker.subprocess.run")
    def test_docker_timeout_fail_closed(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["docker", "compose", "version"], timeout=10
        )
        with tempfile.TemporaryDirectory() as td:
            r = self._worker().execute("scope_code_review", self._action(), Path(td))
        self.assertEqual(r.status, "rejected")
        self.assertIn("sandbox_timeout", r.reason)

    @patch("agora.tool_worker.subprocess.run")
    def test_network_request_denied(self, mock_run: unittest.mock.Mock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["docker", "compose", "version"], returncode=0, stdout="ok\n"
        )
        with tempfile.TemporaryDirectory() as td:
            r = self._worker().execute(
                "scope_code_review",
                self._action(network_request=True),
                Path(td),
            )
        self.assertEqual(r.status, "rejected")
        self.assertIn("sandbox_network_denied", r.reason)


if __name__ == "__main__":
    unittest.main()
