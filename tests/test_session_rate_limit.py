from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class SessionRateLimitTests(unittest.TestCase):
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
        (root / "config" / "operator_policy.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "operator_allow": [],
                    "session_quota": {
                        "max_messages_per_minute": 2,
                        "window_seconds": 1,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def test_session_rate_limit_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-rate"}).json()["session_id"]

            payload = {"command_text": "hello", "raw_features": {"task_intent": "unknown"}}
            r1 = client.post(f"/v1/sessions/{sid}/messages", json=payload)
            r2 = client.post(f"/v1/sessions/{sid}/messages", json=payload)
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)

            r3 = client.post(f"/v1/sessions/{sid}/messages", json=payload)
            self.assertEqual(r3.status_code, 429)
            detail = r3.json()["detail"]
            self.assertEqual(detail["error"], "session_rate_limited")
            self.assertGreaterEqual(int(detail["retry_after_seconds"]), 1)

            time.sleep(1.1)
            r4 = client.post(f"/v1/sessions/{sid}/messages", json=payload)
            self.assertEqual(r4.status_code, 200)


if __name__ == "__main__":
    unittest.main()
