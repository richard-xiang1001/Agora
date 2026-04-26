from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agora.reliability_release_gate import evaluate_reliability_release_gate

ROOT = Path(__file__).resolve().parents[1]


class ReliabilityReleaseGateTests(unittest.TestCase):
    def test_blocks_on_invariant_and_redteam_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = evaluate_reliability_release_gate(
                root=root,
                desktop_report={"status": "passed", "report_path": "desktop.json"},
                invariant_report={"summary": {"critical_count": 1}, "report_path": "invariants.json"},
                redteam_report={"blocked": True, "summary": {"hard_deny_bypass_count": 1}, "report_path": "redteam.json"},
                product_path_report={"blocked": False, "report_path": "product.json"},
                doctor_report={"blocked": False, "schema_migrations": {"passed": True}, "report_path": "doctor.json"},
            )
            blockers = {item["name"] for item in gate["blockers"]}
            self.assertTrue(gate["blocked"])
            self.assertIn("runtime_invariants", blockers)
            self.assertIn("capability_redteam", blockers)

    def test_desktop_cleanup_failure_blocks_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = evaluate_reliability_release_gate(
                root=root,
                desktop_report={
                    "status": "passed",
                    "summary": {"required_count": 3, "required_passed": 3},
                    "cleanup": {"required": True, "passed": False},
                    "report_path": "desktop.json",
                },
                invariant_report={"summary": {"critical_count": 0}, "report_path": "invariants.json"},
                redteam_report={"blocked": False, "summary": {"hard_deny_bypass_count": 0}, "report_path": "redteam.json"},
                product_path_report={"blocked": False, "report_path": "product.json"},
                doctor_report={"blocked": False, "schema_migrations": {"passed": True}, "report_path": "doctor.json"},
            )
            self.assertTrue(gate["blocked"])
            blocker = next(item for item in gate["blockers"] if item["name"] == "desktop_dogfood_gate")
            self.assertFalse(blocker["actual_value"]["cleanup_passed"])

    def test_cli_skip_mode_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir(parents=True)
            (root / "governance/audits").mkdir(parents=True)
            (root / "package.json").write_text(
                '{"build":{"files":["desktop/**/*","package.json"],"extraFiles":[{"from":"agora","to":"backend/agora"}]}}',
                encoding="utf-8",
            )
            (root / "config/permissions_scopes.yaml").write_text("{}", encoding="utf-8")
            (root / "governance/audits/product_path_benchmark.json").write_text("{}", encoding="utf-8")
            (root / "governance/audits/product_path_benchmark_history.jsonl").write_text("", encoding="utf-8")
            (root / "config/product_path_release_gate.yaml").write_text("{}", encoding="utf-8")
            (root / "config/reliability_release_gate.yaml").write_text(
                "thresholds:\n  require_product_path_release_gate_pass: false\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/run_reliability_release_gate.py"),
                    "--root",
                    str(root),
                    "--desktop-mode",
                    "skip",
                ],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertTrue((root / "governance/audits/reliability_release_gate.json").exists())


if __name__ == "__main__":
    unittest.main()
