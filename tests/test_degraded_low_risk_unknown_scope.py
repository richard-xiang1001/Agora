from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app
from agora.audit_daemon import AuditAppendResult


class DegradedLowRiskUnknownScopeTests(unittest.TestCase):
    def _client(self, root: Path) -> TestClient:
        for d in ["policy", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "policy" / "routing_rules.yaml").write_text(
            yaml.safe_dump(
                {
                    "rules": [
                        {
                            "name": "unknown",
                            "priority": 1,
                            "match": {"task_intent": "unknown"},
                            "route": "unknown_workflow",
                            "permissions_scope": "scope_unknown_intersection",
                            "fallback_chain": ["qwen/qwen3-4b:free"],
                            "debate_trigger": {},
                        },
                        {
                            "name": "code_review",
                            "priority": 10,
                            "match": {"task_intent": "code_review"},
                            "route": "code_review_workflow",
                            "permissions_scope": "scope_code_review",
                            "fallback_chain": ["qwen/qwen3-4b:free"],
                            "debate_trigger": {},
                        },
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        return TestClient(create_app(root))

    def _snapshot(self, *, budget_exceeded: bool = False) -> dict[str, object]:
        return {
            "audit_state": "degraded",
            "degraded_since": "2026-02-27T00:00:00+00:00",
            "degraded_seconds": 20,
            "normal_since": None,
            "normal_seconds": 0,
            "degraded_request_count": 2,
            "pending_wal_events": 1,
            "wal_size_bytes": 128,
            "recovery_cooldown_seconds": 120,
            "budget_exceeded": budget_exceeded,
            "last_updated": "2026-02-27T00:00:01+00:00",
            "last_refresh_cause": "append",
        }

    def _append_result(self, *, budget_exceeded: bool = False) -> AuditAppendResult:
        return AuditAppendResult(
            accepted=True,
            duplicate=False,
            seq_no=1,
            wrote_to_wal=True,
            durability_mode="wal",
            audit_state="degraded",
            health_snapshot=self._snapshot(budget_exceeded=budget_exceeded),
        )

    def test_degraded_unknown_low_risk_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-allow"}).json()["session_id"]
            with patch.object(client.app.state.audit_daemon, "append_event", return_value=self._append_result()):
                r = client.post(
                    f"/v1/sessions/{sid}/messages",
                    json={
                        "command_text": "hello",
                        "raw_features": {
                            "task_intent": "unknown",
                            "risk_level": "low",
                            "reversibility": "reversible",
                            "requires_tools": False,
                            "confidence": 0.8,
                        },
                    },
                )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["audit_status"], "degraded")

    def test_degraded_unknown_medium_risk_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-block"}).json()["session_id"]
            with patch.object(client.app.state.audit_daemon, "append_event", return_value=self._append_result()):
                r = client.post(
                    f"/v1/sessions/{sid}/messages",
                    json={
                        "command_text": "hello",
                        "raw_features": {
                            "task_intent": "unknown",
                            "risk_level": "medium",
                            "reversibility": "reversible",
                            "requires_tools": False,
                            "confidence": 0.8,
                        },
                    },
                )
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["detail"], "execution_blocked_audit_degraded")

    def test_degraded_budget_exceeded_blocks_all(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._client(Path(td))
            sid = client.post("/v1/sessions", json={"session_id": "s-budget"}).json()["session_id"]
            with patch.object(
                client.app.state.audit_daemon,
                "append_event",
                return_value=self._append_result(budget_exceeded=True),
            ):
                r = client.post(
                    f"/v1/sessions/{sid}/messages",
                    json={
                        "command_text": "hello",
                        "raw_features": {
                            "task_intent": "unknown",
                            "risk_level": "low",
                            "reversibility": "reversible",
                            "requires_tools": False,
                            "confidence": 0.8,
                        },
                    },
                )
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.json()["detail"], "audit_degraded_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
