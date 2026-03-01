from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


class LintRecoveryPolicyTests(unittest.TestCase):
    def _run_lint(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                "scripts/lint_recovery_policy.py",
                "--path",
                str(path),
                "--schema",
                "governance/recovery_policy_schema.yaml",
            ],
            capture_output=True,
            text=True,
        )

    def test_recovery_policy_lint_passes(self) -> None:
        p = self._run_lint(Path("governance/recovery_policy.yaml"))
        self.assertEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)

    def test_lint_rejects_unknown_trigger_variable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recovery_policy_bad_var.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "rules": [
                            {
                                "id": "bad_var",
                                "metric_source": "audit_health_snapshot",
                                "evaluation_window": {"type": "minutes", "value": 5},
                                "trigger": "unknown_metric > 0",
                                "action": "block_exec_chain",
                                "auto_or_manual": "machine",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            p = self._run_lint(path)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)
            self.assertIn("未知变量 unknown_metric", p.stdout + p.stderr)

    def test_lint_rejects_invalid_trigger_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recovery_policy_bad_syntax.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "rules": [
                            {
                                "id": "bad_syntax",
                                "metric_source": "audit_health_snapshot",
                                "evaluation_window": {"type": "minutes", "value": 5},
                                "trigger": "degraded_seconds >== 300",
                                "action": "block_exec_chain",
                                "auto_or_manual": "machine",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            p = self._run_lint(path)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)
            self.assertIn("trigger 不可解析为合法表达式", p.stdout + p.stderr)

    def test_locked_rules_from_plan_are_machine_evaluable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recovery_policy_locked_rules.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "rules": [
                            {
                                "id": "trigger_audit_degraded_block",
                                "metric_source": "audit_health_snapshot",
                                "evaluation_window": {"type": "minutes", "value": 5},
                                "trigger": "audit_state == 'degraded' AND degraded_seconds >= 300",
                                "action": "block_exec_chain",
                                "auto_or_manual": "machine",
                            },
                            {
                                "id": "trigger_readonly_persistent",
                                "metric_source": "audit_health_snapshot",
                                "evaluation_window": {"type": "instant", "value": 0},
                                "trigger": "audit_state == 'readonly'",
                                "action": "block_exec_chain",
                                "auto_or_manual": "machine",
                            },
                            {
                                "id": "trigger_wal_capacity",
                                "metric_source": "audit_wal_size_bytes",
                                "evaluation_window": {"type": "instant", "value": 0},
                                "trigger": "wal_size_bytes >= 536870912",
                                "action": "readonly_mode",
                                "auto_or_manual": "machine",
                            },
                            {
                                "id": "trigger_discovery_fail",
                                "metric_source": "script_exit_code",
                                "evaluation_window": {"type": "runs", "value": 1},
                                "trigger": "discovery_gate_exit_code != 0",
                                "action": "switch_to_72h_branch",
                                "auto_or_manual": "machine",
                            },
                            {
                                "id": "trigger_l3_false_positive",
                                "metric_source": "audit_event_count",
                                "evaluation_window": {"type": "runs", "value": 1},
                                "trigger": "code_review_blocked_rate > 0.95 AND hard_constraint_hit_rate == 0",
                                "action": "route_to_needs_review_text_mode",
                                "auto_or_manual": "machine",
                            },
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            p = self._run_lint(path)
            self.assertEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)

    def test_manual_rule_requires_escalation_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recovery_policy_manual_missing.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "rules": [
                            {
                                "id": "manual_missing",
                                "metric_source": "failure_mode_endpoint",
                                "evaluation_window": {"type": "runs", "value": 1},
                                "trigger": "audit_state == 'degraded'",
                                "action": "manual_review",
                                "auto_or_manual": "manual",
                                "max_response_minutes": 30,
                                "evidence_path": "governance/audits/evidence.md",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            p = self._run_lint(path)
            self.assertNotEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)
            self.assertIn("escalation_to_machine_date", p.stdout + p.stderr)

    def test_manual_rule_with_escalation_fields_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "recovery_policy_manual_ok.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "rules": [
                            {
                                "id": "manual_ok",
                                "metric_source": "failure_mode_endpoint",
                                "evaluation_window": {"type": "runs", "value": 1},
                                "trigger": "audit_state == 'degraded'",
                                "action": "manual_review",
                                "auto_or_manual": "manual",
                                "max_response_minutes": 30,
                                "evidence_path": "governance/audits/evidence.md",
                                "escalation_to_machine_date": "tbd",
                            }
                        ],
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            p = self._run_lint(path)
            self.assertEqual(p.returncode, 0, msg=p.stdout + "\n" + p.stderr)
            self.assertIn("[WARN]", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
