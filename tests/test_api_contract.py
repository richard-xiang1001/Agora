from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app
from agora.audit_daemon import sign_request


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in [
            "policy",
            "config",
            "sessions",
            "governance",
            "governance/redteam",
            "redteam",
            "audit/wal",
            "indexes",
        ]:
            (self.root / d).mkdir(parents=True, exist_ok=True)

        (self.root / "policy" / "routing_rules.yaml").write_text(
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
                            "debate_trigger": {
                                "risk_level": ["high"],
                                "subagent_disagreement": True,
                            },
                        },
                        {
                            "name": "unknown",
                            "priority": 999,
                            "match": {"task_intent": "unknown"},
                            "route": "unknown_workflow",
                            "permissions_scope": "scope_unknown_intersection",
                            "fallback_chain": ["meta-llama/llama-3.3-70b-instruct:free"],
                            "debate_trigger": {"risk_level": ["high"]},
                        },
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (self.root / "governance" / "traceability.yaml").write_text(
            yaml.safe_dump(
                {
                    "constitution_version": "v0.1",
                    "test_threshold_version": "v0.1",
                    "entries": [
                        {
                            "clause_id": "4.1",
                            "behavioral": True,
                            "modules": ["policy/hard_constraints.py"],
                            "tests": ["tests/test_hard_constraints.py"],
                            "coverage_note": "sample",
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (self.root / "redteam" / "suite.yaml").write_text(
            yaml.safe_dump(
                {
                    "categories": [
                        {
                            "name": "hard_constraint",
                            "samples": 1,
                            "detected": 1,
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (self.root / "redteam" / "thresholds.yaml").write_text(
            yaml.safe_dump(
                {
                    "hard_constraint": {"block_rate": 1.0},
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        (self.root / "config" / "llm_policy.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0",
                    "provider": "openrouter",
                    "mode": "mock",
                    "model": "upstage/solar-pro-3:free",
                    "timeout_seconds": 30,
                    "max_retries": 2,
                    "retry_on": [500, 502, 503],
                    "fallback_on_error": False,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        self.client = TestClient(create_app(self.root))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_session_message_and_workflow_controls(self) -> None:
        sid = self.client.post("/v1/sessions", json={"session_id": "s-1"}).json()["session_id"]
        self.assertEqual(sid, "s-1")

        msg = self.client.post(
            f"/v1/sessions/{sid}/messages",
            json={
                "command_text": "review this patch",
                "raw_features": {
                    "task_intent": "code_review",
                    "risk_level": "high",
                    "reversibility": "partial",
                    "requires_tools": False,
                    "confidence": 0.9,
                },
                "subagent_disagreement": False,
            },
        )
        self.assertEqual(msg.status_code, 200)
        wf = msg.json()["workflow_id"]
        self.assertEqual(msg.json()["prompt_profile_id"], "profile.debate_code_review")
        self.assertTrue(isinstance(msg.json()["prompt_binding_hash"], str))
        self.assertEqual(msg.json()["execution_mode"], "debate")
        self.assertIsNone(msg.json().get("verdict"))
        self.assertIn("debate_verdict", msg.json())

        status = self.client.get(f"/v1/workflows/{wf}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["routing"]["workflow_type"], "code_review_workflow")
        self.assertEqual(status.json()["prompt_binding"]["profile_id"], "profile.debate_code_review")
        self.assertTrue(isinstance(status.json()["prompt_binding"]["binding_hash"], str))
        self.assertEqual(status.json()["execution_mode"], "debate")
        self.assertIn("debate_verdict", status.json())

        paused = self.client.post(f"/v1/workflows/{wf}/pause").json()
        self.assertEqual(paused["status"], "paused")
        resumed = self.client.post(f"/v1/workflows/{wf}/resume").json()
        self.assertEqual(resumed["status"], "running")

    def test_code_review_low_risk_uses_subagent_path(self) -> None:
        sid = self.client.post("/v1/sessions", json={"session_id": "s-2"}).json()["session_id"]
        msg = self.client.post(
            f"/v1/sessions/{sid}/messages",
            json={
                "command_text": "review small patch",
                "raw_features": {
                    "task_intent": "code_review",
                    "risk_level": "low",
                    "reversibility": "reversible",
                    "requires_tools": False,
                    "confidence": 0.9,
                },
                "subagent_disagreement": False,
            },
        )
        self.assertEqual(msg.status_code, 200)
        body = msg.json()
        self.assertEqual(body["execution_mode"], "subagent")
        self.assertIn("verdict", body)
        self.assertIsNone(body.get("debate_verdict"))

        wf = body["workflow_id"]
        status = self.client.get(f"/v1/workflows/{wf}")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["execution_mode"], "subagent")
        self.assertIn("verdict", status.json())

    def test_subagent_disagreement_triggers_debate_on_low_risk(self) -> None:
        sid = self.client.post("/v1/sessions", json={"session_id": "s-3"}).json()["session_id"]
        msg = self.client.post(
            f"/v1/sessions/{sid}/messages",
            json={
                "command_text": "review disagreement patch",
                "raw_features": {
                    "task_intent": "code_review",
                    "risk_level": "low",
                    "reversibility": "reversible",
                    "requires_tools": False,
                    "confidence": 0.9,
                },
                "subagent_disagreement": True,
            },
        )
        self.assertEqual(msg.status_code, 200)
        body = msg.json()
        self.assertEqual(body["execution_mode"], "debate")
        self.assertIn("debate_verdict", body)

    def test_route_preview_and_internal_audit(self) -> None:
        route = self.client.post(
            "/v1/route/preview",
            json={
                "command_text": "random text",
                "raw_features": {"task_intent": "INVALID"},
            },
        )
        self.assertEqual(route.status_code, 200)
        body = route.json()
        self.assertEqual(body["gate_state"], "degraded_to_unknown")
        self.assertEqual(body["final_route"]["workflow_type"], "unknown_workflow")

        req = sign_request(
            component_id="gateway",
            key_id="key_v1",
            secret="dev-secret-gateway",
            event_id=str(uuid.uuid4()),
            event_type="route_preview",
            payload={"route": "unknown"},
        )
        appended = self.client.post("/internal/audit/append", json=req.model_dump(mode="json"))
        self.assertEqual(appended.status_code, 200)
        self.assertTrue(appended.json()["accepted"])


if __name__ == "__main__":
    unittest.main()
