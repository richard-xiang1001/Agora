from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class SessionBudgetTests(unittest.TestCase):
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

    def test_set_and_get_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = self._client(root)
            sid = client.post("/v1/sessions", json={"session_id": "s-budget"}).json()["session_id"]

            set_resp = client.post(
                f"/v1/sessions/{sid}/budget",
                json={"max_cost_usd": 0.5, "max_tokens": 50000},
            )
            self.assertEqual(set_resp.status_code, 200)
            body = set_resp.json()["budget"]
            self.assertEqual(body["max_cost_usd"], 0.5)
            self.assertEqual(body["max_tokens"], 50000)
            self.assertEqual(body["consumed_tokens"], 0)

            get_resp = client.get(f"/v1/sessions/{sid}/budget")
            self.assertEqual(get_resp.status_code, 200)
            self.assertEqual(get_resp.json()["budget"]["max_tokens"], 50000)

    def test_budget_exceeded_blocks_submit_and_writes_audit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            client = self._client(root)
            sid = client.post("/v1/sessions", json={"session_id": "s-budget-exceeded"}).json()["session_id"]

            client.post(
                f"/v1/sessions/{sid}/budget",
                json={"max_cost_usd": 0.001, "max_tokens": 50},
            )
            budget_path = root / "sessions" / sid / "budget.json"
            budget = json.loads(budget_path.read_text(encoding="utf-8"))
            budget["consumed_cost_usd"] = 0.001
            budget["consumed_tokens"] = 0
            budget_path.write_text(json.dumps(budget, ensure_ascii=True, indent=2), encoding="utf-8")

            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={"command_text": "hello", "raw_features": {"task_intent": "unknown"}},
            )
            self.assertEqual(resp.status_code, 429)
            self.assertEqual(resp.json()["detail"], "budget_exceeded")

            log_path = root / "audit" / "audit.jsonl"
            text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            self.assertIn("session_budget_exceeded", text)


if __name__ == "__main__":
    unittest.main()
