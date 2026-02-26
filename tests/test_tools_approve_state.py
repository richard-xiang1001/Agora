from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class ToolsApproveStateTests(unittest.TestCase):
    def test_tools_approve_persists_state(self) -> None:
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
            sid = client.post("/v1/sessions", json={"session_id": "s-tools"}).json()["session_id"]
            wf = client.post(
                f"/v1/sessions/{sid}/messages",
                json={"command_text": "hi", "raw_features": {"task_intent": "unknown"}},
            ).json()["workflow_id"]

            resp = client.post(
                "/v1/tools/approve",
                json={
                    "workflow_id": wf,
                    "action_id": "act-1",
                    "approved": True,
                    "operator_id": "op-1",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "approved")

            approval = json.loads(
                (root / "sessions" / sid / "workflows" / wf / "approval.json").read_text(encoding="utf-8")
            )
            self.assertEqual(approval["actions"]["act-1"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
