from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class Week11ApiExtensionsTests(unittest.TestCase):
    def _client(self, root: Path) -> TestClient:
        for d in ["policy", "config", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "policy" / "routing_rules.yaml").write_text(
            yaml.safe_dump({"rules": [{"name": "unknown", "priority": 1, "match": {"task_intent": "unknown"}, "route": "unknown_workflow", "permissions_scope": "scope_unknown_intersection", "fallback_chain": ["qwen/qwen3-4b:free"], "debate_trigger": {}}]}, sort_keys=False),
            encoding="utf-8",
        )
        (root / "config" / "llm_policy.yaml").write_text(
            yaml.safe_dump({"schema_version": "1.0", "provider": "openrouter", "mode": "mock", "model": "qwen/qwen3-4b:free", "timeout_seconds": 30, "max_retries": 1, "retry_on": [500], "fallback_on_error": False}, sort_keys=False),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def test_runtime_status_and_initiative_policy_get(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            c = self._client(Path(td))
            sid = c.post("/v1/sessions", json={"session_id": "s1"}).json()["session_id"]

            st = c.get("/v1/runtime/status")
            self.assertEqual(st.status_code, 200)
            self.assertIn("running", st.json())

            setp = c.post(
                f"/v1/sessions/{sid}/initiative/policy",
                json={"mode": "manual_confirm", "max_auto_actions_per_hour": 1, "require_human_on_budget_exceeded": True},
            )
            self.assertEqual(setp.status_code, 200)
            getp = c.get(f"/v1/sessions/{sid}/initiative/policy")
            self.assertEqual(getp.status_code, 200)
            self.assertEqual(getp.json()["initiative_policy"]["mode"], "manual_confirm")


if __name__ == "__main__":
    unittest.main()
