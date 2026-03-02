from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class HardConstraintGuardExceptionTests(unittest.TestCase):
    def test_guard_exception_is_fail_closed_503(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ["policy", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
                (root / d).mkdir(parents=True, exist_ok=True)

            (root / "policy" / "routing_rules.yaml").write_text(
                yaml.safe_dump(
                    {
                        "rules": [
                            {
                                "name": "unknown",
                                "priority": 999,
                                "match": {"task_intent": "unknown"},
                                "route": "unknown_workflow",
                                "permissions_scope": "scope_unknown_intersection",
                                "fallback_chain": ["qwen/qwen3-4b:free"],
                                "debate_trigger": {},
                            }
                        ]
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "config" / "llm_policy.yaml").write_text(
                yaml.safe_dump(
                    {
                        "schema_version": "1.0",
                        "provider": "openrouter",
                        "mode": "mock",
                        "model": "qwen/qwen3-4b:free",
                        "timeout_seconds": 30,
                        "max_retries": 1,
                        "retry_on": [500, 502, 503],
                        "fallback_on_error": False,
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            client = TestClient(create_app(root))
            sid = client.post("/v1/sessions", json={"session_id": "s-guard-ex"}).json()["session_id"]

            with patch("agora.controllers.message_controller.check_hard_constraints", side_effect=RuntimeError("boom")):
                resp = client.post(
                    f"/v1/sessions/{sid}/messages",
                    json={"command_text": "hello", "raw_features": {"task_intent": "unknown"}},
                )

            self.assertEqual(resp.status_code, 503)
            self.assertEqual(resp.json().get("detail"), "hard_constraint_guard_error")


if __name__ == "__main__":
    unittest.main()
