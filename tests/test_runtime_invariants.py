from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agora.runtime_invariants import check_runtime_invariants


class _DeadProcess:
    def poll(self) -> int:
        return 0


class RuntimeInvariantTests(unittest.TestCase):
    def test_detects_team_config_and_approval_actor_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "runtime" / "agent_team_tasks"
            task_dir.mkdir(parents=True)
            (task_dir / "team-1.json").write_text(
                json.dumps(
                    {
                        "team_run_id": "team-1",
                        "member_runs": [{"member_id": "research", "permission_mode": "read_only"}],
                        "tasks": [{"member_id": "research", "permission_mode": "full_access"}],
                    }
                ),
                encoding="utf-8",
            )
            actor_dir = root / "runtime" / "agent_team_approval_actors"
            actor_dir.mkdir(parents=True)
            (actor_dir / "team-1.jsonl").write_text(
                json.dumps({"actor_id": "actor-1", "status": "pending", "workflow_id": "wf-1", "action_id": "act-1"}) + "\n",
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, write_report=False)
            categories = {item["category"] for item in report["findings"]}
            self.assertTrue(report["blocked"])
            self.assertIn("team_runtime_config_mismatch", categories)
            self.assertIn("approval_actor_orphan", categories)
            self.assertEqual(report["summary"]["critical_count"], 2)

    def test_repair_safe_unregisters_dead_process_without_deleting_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = SimpleNamespace(state=SimpleNamespace(runtime_task_processes={"task-dead": _DeadProcess()}, runtime_task_native_panes={}))
            report = check_runtime_invariants(app=app, root=root, mode="repair-safe", write_report=False)
            self.assertEqual(report["summary"]["repairs_applied"], 1)
            self.assertNotIn("task-dead", app.state.runtime_task_processes)
            self.assertTrue((root / "governance/audits/runtime_invariant_repair_ledger.jsonl").exists())

    def test_provider_raw_imbalance_is_warning_not_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sidechain = root / "runtime" / "agent_sidechains"
            sidechain.mkdir(parents=True)
            (sidechain / "agent-a.jsonl").write_text(
                json.dumps({"kind": "provider_raw_request", "call_id": "call-1"}) + "\n",
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, write_report=False)
            self.assertFalse(report["blocked"])
            self.assertEqual(report["summary"]["warning_count"], 1)

    def test_pending_action_without_approval_actor_is_critical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            (wf_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {"pending_actions": [{"workflow_id": "wf-1", "action_id": "act-1"}]},
                    }
                ),
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, write_report=False)
            categories = {item["category"] for item in report["findings"]}
            self.assertTrue(report["blocked"])
            self.assertIn("workflow_pending_action_missing_approval_actor", categories)

    def test_legacy_pending_action_reason_is_non_blocking_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            (wf_dir / "workflow.json").write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {
                            "pending_actions": [
                                {
                                    "workflow_id": "wf-1",
                                    "action_id": "act-1",
                                    "action": "manual_review",
                                    "approval_actor_legacy_reason": "legacy_manual_review_gate_pre_approval_actor",
                                    "legacy_migration_id": "runtime_invariants_legacy_pending_action_v1",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, write_report=False)
            self.assertFalse(report["blocked"])
            self.assertEqual(report["summary"]["critical_count"], 0)
            self.assertEqual(report["summary"]["legacy_safe_pending_action_count"], 1)
            self.assertEqual(report["legacy_safe_pending_actions"][0]["migration_id"], "runtime_invariants_legacy_pending_action_v1")

    def test_mark_legacy_safe_dry_run_plans_without_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            workflow_path = wf_dir / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {
                            "pending_actions": [
                                {
                                    "workflow_id": "wf-1",
                                    "action_id": "act-1",
                                    "action": "manual_review",
                                    "status": "pending_approval",
                                    "reason": "waiting_for_user_review",
                                    "approval_required": True,
                                    "approval_source": "manual_review_gate",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False)
            self.assertFalse(report["blocked"])
            self.assertEqual(report["summary"]["repairs_applied"], 0)
            self.assertEqual(report["summary"]["legacy_safe_pending_action_count"], 1)
            self.assertEqual(report["summary"]["planned_legacy_mutation_count"], 1)
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            action = workflow["chat_result"]["pending_actions"][0]
            self.assertEqual(action["status"], "pending_approval")
            self.assertEqual(action["reason"], "waiting_for_user_review")
            self.assertTrue(action["approval_required"])
            self.assertNotIn("approval_actor_id", action)
            self.assertNotIn("approval_actor_legacy_reason", action)
            self.assertFalse((root / "governance/audits/runtime_invariant_repair_ledger.jsonl").exists())

    def test_mark_legacy_safe_write_marks_only_manual_review_without_changing_business_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            workflow_path = wf_dir / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {
                            "pending_actions": [
                                {
                                    "workflow_id": "wf-1",
                                    "action_id": "act-1",
                                    "action": "manual_review",
                                    "status": "pending_approval",
                                    "reason": "waiting_for_user_review",
                                    "approval_required": True,
                                    "approval_source": "manual_review_gate",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False, legacy_write=True)
            self.assertFalse(report["blocked"])
            self.assertEqual(report["summary"]["repairs_applied"], 1)
            self.assertEqual(report["summary"]["legacy_safe_pending_action_count"], 1)
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            action = workflow["chat_result"]["pending_actions"][0]
            self.assertEqual(action["status"], "pending_approval")
            self.assertEqual(action["reason"], "waiting_for_user_review")
            self.assertTrue(action["approval_required"])
            self.assertNotIn("approval_actor_id", action)
            self.assertEqual(action["approval_actor_legacy_reason"], "legacy_manual_review_gate_pre_approval_actor")
            self.assertEqual(action["legacy_migration_id"], "runtime_invariants_legacy_pending_action_v1")
            ledger_path = root / "governance/audits/runtime_invariant_repair_ledger.jsonl"
            ledger = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(ledger[0]["action"], "mark_workflow_pending_action_legacy")
            self.assertTrue(ledger[0]["non_destructive"])
            self.assertIn("before", ledger[0])
            self.assertIn("after", ledger[0])

    def test_mark_legacy_safe_write_is_idempotent_unless_forced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            workflow_path = wf_dir / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {
                            "pending_actions": [
                                {
                                    "workflow_id": "wf-1",
                                    "action_id": "act-1",
                                    "action": "manual_review",
                                    "approval_source": "manual_review_gate",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            first = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False, legacy_write=True)
            self.assertEqual(first["summary"]["repairs_applied"], 1)
            action = json.loads(workflow_path.read_text(encoding="utf-8"))["chat_result"]["pending_actions"][0]
            marked_at = action["legacy_marked_at"]
            ledger_path = root / "governance/audits/runtime_invariant_repair_ledger.jsonl"
            self.assertEqual(len(ledger_path.read_text(encoding="utf-8").splitlines()), 1)

            second = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False, legacy_write=True)
            self.assertEqual(second["summary"]["repairs_applied"], 0)
            action = json.loads(workflow_path.read_text(encoding="utf-8"))["chat_result"]["pending_actions"][0]
            self.assertEqual(action["legacy_marked_at"], marked_at)
            self.assertEqual(len(ledger_path.read_text(encoding="utf-8").splitlines()), 1)

            forced = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False, legacy_write=True, legacy_force=True)
            self.assertEqual(forced["summary"]["repairs_applied"], 1)
            self.assertEqual(len(ledger_path.read_text(encoding="utf-8").splitlines()), 2)

    def test_mark_legacy_safe_does_not_mark_non_manual_review_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf_dir = root / "sessions" / "s1" / "workflows" / "wf-1"
            wf_dir.mkdir(parents=True)
            workflow_path = wf_dir / "workflow.json"
            workflow_path.write_text(
                json.dumps(
                    {
                        "workflow_id": "wf-1",
                        "status": "waiting_user",
                        "chat_result": {
                            "pending_actions": [
                                {
                                    "workflow_id": "wf-1",
                                    "action_id": "act-1",
                                    "action": "shell_exec",
                                    "status": "pending_approval",
                                    "approval_required": True,
                                    "approval_source": "tool_permission",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = check_runtime_invariants(app=None, root=root, mode="mark-legacy-safe", write_report=False)
            self.assertTrue(report["blocked"])
            self.assertEqual(report["summary"]["critical_count"], 1)
            workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
            action = workflow["chat_result"]["pending_actions"][0]
            self.assertNotIn("approval_actor_legacy_reason", action)
            self.assertFalse((root / "governance/audits/runtime_invariant_repair_ledger.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
