from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class BudgetPolicyTests(unittest.TestCase):
    def _client(self, root: Path) -> TestClient:
        for d in ["policy", "config", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
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
        return TestClient(create_app(root))

    def test_get_and_set_budget_policy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-budget-policy"}).json()["session_id"]

            r0 = client.get(f"/v1/sessions/{sid}/budget/policy")
            self.assertEqual(r0.status_code, 200)
            self.assertEqual(r0.json()["budget_policy"]["on_exceeded"], "block")

            r1 = client.post(
                f"/v1/sessions/{sid}/budget/policy",
                json={"on_exceeded": "degrade_to_mock", "degrade_model": "mock", "grace_requests": 2},
            )
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r1.json()["budget_policy"]["on_exceeded"], "degrade_to_mock")
            self.assertEqual(r1.json()["budget_policy"]["grace_requests"], 2)

            r2 = client.get(f"/v1/sessions/{sid}/budget/policy")
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()["budget_policy"]["on_exceeded"], "degrade_to_mock")


if __name__ == "__main__":
    unittest.main()
