from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app
from agora.audit_daemon import sign_request


class AuditScrubTests(unittest.TestCase):
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

    def test_scrub_truncates_sensitive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            os.environ["AGORA_INTERNAL_API_TOKEN"] = "scrub-token"
            client = self._client(root)

            big_diff = "D" * 501
            req = sign_request(
                component_id="gateway",
                key_id="key_v1",
                secret="dev-secret-gateway",
                event_id=str(uuid.uuid4()),
                event_type="scrub_test",
                payload={
                    "diff": big_diff,
                    "error_message": big_diff + "_error",
                    "stderr_tail": "E" * 450,
                },
            )
            resp = client.post(
                "/internal/audit/append",
                json=req.model_dump(mode="json"),
                headers={"X-Agora-Internal-Token": "scrub-token"},
            )
            self.assertEqual(resp.status_code, 200)

            rows = [
                json.loads(line)
                for line in (root / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            payload = rows[-1]["payload"]
            self.assertTrue(payload["diff"].startswith("D" * 500))
            self.assertIn("[scrubbed:501]", payload["diff"])
            self.assertIn("scrubbed_fields", payload)
            self.assertIn("diff", payload["scrubbed_fields"])
            self.assertTrue(payload.get("scrub_triggered"))
            self.assertNotIn(big_diff, payload["error_message"])
            self.assertIn("[scrubbed:", payload["error_message"])

            os.environ.pop("AGORA_INTERNAL_API_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
