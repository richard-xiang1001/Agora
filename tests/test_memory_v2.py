from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class MemoryV2Tests(unittest.TestCase):
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

    def test_ingest_query_decay_stats(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c = self._client(root)
            sid = c.post("/v1/sessions", json={"session_id": "s-mem"}).json()["session_id"]

            r1 = c.post(f"/v1/sessions/{sid}/memory/ingest", json={"layer": "episodic", "content": "fixed auth bug", "source": "wf:1", "confidence": 0.9, "tags": ["auth"]})
            self.assertEqual(r1.status_code, 200)
            self.assertTrue(r1.json()["inserted"])

            r2 = c.post(f"/v1/sessions/{sid}/memory/ingest", json={"layer": "episodic", "content": "fixed auth bug", "source": "wf:1", "confidence": 0.9, "tags": ["auth"]})
            self.assertEqual(r2.status_code, 200)
            self.assertFalse(r2.json()["inserted"])

            q = c.post(f"/v1/sessions/{sid}/memory/query", json={"query": "auth bug", "top_k": 5})
            self.assertEqual(q.status_code, 200)
            self.assertGreaterEqual(len(q.json()["hits"]), 1)
            self.assertIn("hit_path", q.json()["hits"][0])

            d = c.post(f"/v1/sessions/{sid}/memory/decay/run")
            self.assertEqual(d.status_code, 200)
            self.assertGreaterEqual(d.json()["decayed_count"], 1)

            s = c.get(f"/v1/sessions/{sid}/memory/stats")
            self.assertEqual(s.status_code, 200)
            self.assertEqual(s.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
