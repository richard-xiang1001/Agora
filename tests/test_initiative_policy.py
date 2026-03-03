from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app


class InitiativePolicyTests(unittest.TestCase):
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
            yaml.safe_dump({"schema_version": "1.0", "provider": "openrouter", "mode": "mock", "model": "qwen/qwen3-4b:free", "timeout_seconds": 30, "max_retries": 1, "retry_on": [500], "fallback_on_error": False}, sort_keys=False),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def test_suggest_only_proposed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            c = self._client(Path(td))
            sid = c.post("/v1/sessions", json={"session_id": "s1"}).json()["session_id"]
            c.post(f"/v1/sessions/{sid}/initiative/policy", json={"mode": "suggest_only", "max_auto_actions_per_hour": 3, "require_human_on_budget_exceeded": True})
            msg = c.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this patch",
                    "raw_features": {"task_intent": "code_review", "risk_level": "low", "reversibility": "reversible", "requires_tools": False, "confidence": 0.9},
                },
            )
            self.assertEqual(msg.status_code, 200)
            self.assertEqual(msg.json()["initiative_status"], "proposed")

    def test_auto_low_risk_blocked_when_high_risk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            c = self._client(Path(td))
            sid = c.post("/v1/sessions", json={"session_id": "s2"}).json()["session_id"]
            c.post(f"/v1/sessions/{sid}/initiative/policy", json={"mode": "auto_low_risk", "max_auto_actions_per_hour": 3, "require_human_on_budget_exceeded": True})
            msg = c.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review this risky patch",
                    "raw_features": {"task_intent": "code_review", "risk_level": "high", "reversibility": "partial", "requires_tools": False, "confidence": 0.9},
                },
            )
            self.assertEqual(msg.status_code, 200)
            self.assertEqual(msg.json()["initiative_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
