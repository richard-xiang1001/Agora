from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class TraceEventSchemaConsistencyTests(unittest.TestCase):
    def test_workflow_created_event_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ["policy", "sessions", "governance", "governance/redteam", "redteam", "audit/wal"]:
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
            client = TestClient(create_app(root))
            sid = client.post("/v1/sessions", json={"session_id": "s-trace"}).json()["session_id"]
            wf = client.post(
                f"/v1/sessions/{sid}/messages",
                json={"command_text": "hello", "raw_features": {"task_intent": "unknown"}},
            ).json()["workflow_id"]

            rows = [
                json.loads(x)
                for x in (root / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
                if x.strip()
            ]
            row = rows[-1]
            self.assertIn("event_id", row)
            self.assertIn("seq_no", row)
            self.assertIn("trace_id", row)
            self.assertIn("component_id", row)
            self.assertIn("event_type", row)
            self.assertEqual(row["payload"]["workflow_id"], wf)


if __name__ == "__main__":
    unittest.main()
