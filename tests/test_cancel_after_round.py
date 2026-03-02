from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class CancelAfterRoundTests(unittest.TestCase):
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
                    "debate": {
                        "max_parallel_roles": 3,
                        "round_timeout_seconds": 30,
                        "round2_claim_char_limit": 400,
                        "round2_payload_char_limit": 3500,
                        "round3_payload_char_limit": 5000,
                    },
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def test_cancel_after_round_1(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-cancel-r1"}).json()["session_id"]
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this patch",
                    "cancel_after_round": 1,
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "high",
                        "reversibility": "partial",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body.get("workflow_status"), "cancelled")
            self.assertEqual(body.get("cancelled_at_round"), 1)

    def test_cancel_after_round_3_equals_normal_completion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-cancel-r3"}).json()["session_id"]
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this patch",
                    "cancel_after_round": 3,
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "high",
                        "reversibility": "partial",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body.get("workflow_status"), "completed")
            self.assertIsNone(body.get("cancelled_at_round"))


if __name__ == "__main__":
    unittest.main()
