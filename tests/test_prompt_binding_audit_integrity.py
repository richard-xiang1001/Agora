from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agora.api import create_app
from agora.prompt_registry import compose_binding_hash, load_catalog


class PromptBindingAuditIntegrityTests(unittest.TestCase):
    def test_workflow_prompt_binding_hash_matches_registry_assets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ["policy", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "config"]:
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

            client = TestClient(create_app(root))
            sid = client.post("/v1/sessions", json={"session_id": "s-bind"}).json()["session_id"]
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={"command_text": "hello", "raw_features": {"task_intent": "unknown"}},
            )
            self.assertEqual(resp.status_code, 200)
            wf = resp.json()["workflow_id"]
            data = json.loads((root / "sessions" / sid / "workflows" / wf / "workflow.json").read_text("utf-8"))

            registry = load_catalog("config/prompt_catalog.yaml")
            profile_id = data["prompt_binding"]["profile_id"]
            assets = (
                registry.resolve_profile(profile_id)
                if profile_id.startswith("profile.")
                else [registry.get_prompt(profile_id)]
            )
            self.assertEqual(data["prompt_binding"]["binding_hash"], compose_binding_hash(assets))

    def test_code_review_binding_hash_matches_and_verdict_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for d in ["policy", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "config"]:
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

            client = TestClient(create_app(root))
            sid = client.post("/v1/sessions", json={"session_id": "s-bind-cr"}).json()["session_id"]
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": "review diff\n+print('x')\n",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            self.assertEqual(resp.status_code, 200)
            wf = resp.json()["workflow_id"]
            data = json.loads((root / "sessions" / sid / "workflows" / wf / "workflow.json").read_text("utf-8"))

            registry = load_catalog("config/prompt_catalog.yaml")
            profile_id = data["prompt_binding"]["profile_id"]
            assets = (
                registry.resolve_profile(profile_id)
                if profile_id.startswith("profile.")
                else [registry.get_prompt(profile_id)]
            )
            self.assertEqual(data["prompt_binding"]["binding_hash"], compose_binding_hash(assets))
            self.assertIn("verdict", data)


if __name__ == "__main__":
    unittest.main()
