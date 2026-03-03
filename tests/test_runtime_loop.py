from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class RuntimeLoopTests(unittest.TestCase):
    def _mk(self, root: Path) -> TestClient:
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
                    "retry_on": [500],
                    "fallback_on_error": False,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def test_runtime_enqueue_and_process(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c = self._mk(root)
            sid = c.post("/v1/sessions", json={"session_id": "s1"}).json()["session_id"]
            enq = c.post(
                f"/v1/sessions/{sid}/tasks",
                json={
                    "command_text": "review queued patch",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(enq.status_code, 200)
            task_id = enq.json()["task_id"]
            start = c.post("/v1/runtime/start")
            self.assertEqual(start.status_code, 200)

            task = c.get(f"/v1/sessions/{sid}/tasks/{task_id}")
            self.assertEqual(task.status_code, 200)
            self.assertEqual(task.json()["status"], "completed")
            self.assertEqual(task.json()["response"]["runtime_mode"], "queued_runtime")

    def test_runtime_recovery_clears_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c = self._mk(root)
            sid = c.post("/v1/sessions", json={"session_id": "s2"}).json()["session_id"]
            c.post(
                f"/v1/sessions/{sid}/tasks",
                json={
                    "command_text": "review patch recover",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            cp = root / "runtime" / "checkpoint.json"
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text('{"task_id":"task_x","status":"running"}', encoding="utf-8")

            c2 = self._mk(root)
            resp = c2.post("/v1/runtime/start")
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(cp.exists())


if __name__ == "__main__":
    unittest.main()
