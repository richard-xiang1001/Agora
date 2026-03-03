from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class BudgetPolicyDegradedExecutionTests(unittest.TestCase):
    def _client(self, root: Path) -> TestClient:
        for d in ["policy", "config", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "policy" / "routing_rules.yaml").write_text(
            yaml.safe_dump(
                {
                    "rules": [
                        {
                            "name": "code_review",
                            "priority": 10,
                            "match": {"task_intent": "code_review"},
                            "route": "code_review_workflow",
                            "permissions_scope": "scope_code_review",
                            "fallback_chain": ["qwen/qwen3-4b:free"],
                            "debate_trigger": {"risk_level": ["high"]},
                        },
                        {
                            "name": "unknown",
                            "priority": 999,
                            "match": {"task_intent": "unknown"},
                            "route": "unknown_workflow",
                            "permissions_scope": "scope_unknown_intersection",
                            "fallback_chain": ["qwen/qwen3-4b:free"],
                            "debate_trigger": {},
                        },
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

    def _force_budget_exceeded(self, root: Path, sid: str) -> None:
        budget_path = root / "sessions" / sid / "budget.json"
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
        budget["consumed_cost_usd"] = 1.0
        budget["consumed_tokens"] = 1000
        budget_path.write_text(json.dumps(budget, ensure_ascii=True, indent=2), encoding="utf-8")

    def test_degrade_to_mock_mode_returns_200(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = self._client(root)
            sid = client.post("/v1/sessions", json={"session_id": "s-budget-degrade"}).json()["session_id"]
            client.post(f"/v1/sessions/{sid}/budget", json={"max_cost_usd": 0.001, "max_tokens": 1})
            self._force_budget_exceeded(root, sid)
            client.post(
                f"/v1/sessions/{sid}/budget/policy",
                json={"on_exceeded": "degrade_to_mock", "degrade_model": "mock", "grace_requests": 0},
            )

            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this patch",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertTrue(body["degraded_execution"])
            self.assertEqual(body["budget_policy_applied"], "degrade_to_mock")
            self.assertEqual(body["execution_mode"], "degraded_mock")

    def test_allow_with_audit_mode_returns_200_without_degraded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = self._client(root)
            sid = client.post("/v1/sessions", json={"session_id": "s-budget-allow"}).json()["session_id"]
            client.post(f"/v1/sessions/{sid}/budget", json={"max_cost_usd": 0.001, "max_tokens": 1})
            self._force_budget_exceeded(root, sid)
            client.post(
                f"/v1/sessions/{sid}/budget/policy",
                json={"on_exceeded": "allow_with_audit", "degrade_model": "mock", "grace_requests": 0},
            )

            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this patch",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertFalse(body["degraded_execution"])
            self.assertEqual(body["budget_policy_applied"], "allow_with_audit")


if __name__ == "__main__":
    unittest.main()
