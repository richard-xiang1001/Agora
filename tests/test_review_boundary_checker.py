from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True, timeout=30)


class ReviewBoundaryCheckerTests(unittest.TestCase):
    def test_checker_reports_review_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            for path in (
                "agora/runtime_invariants.py",
                "scripts/desktop_pack_preflight.py",
                "tests/test_release_hygiene.py",
                "governance/audits/reliability_release_gate.json",
            ):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_review_boundary.py"),
                    "--root",
                    str(root),
                    "--json",
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertIn("agora/runtime_invariants.py", report["groups"]["commit_a"])
            self.assertIn("scripts/desktop_pack_preflight.py", report["groups"]["commit_b"])
            self.assertIn("tests/test_release_hygiene.py", report["groups"]["commit_c"])
            self.assertIn("governance/audits/reliability_release_gate.json", report["groups"]["evidence"])

    def test_strict_fails_when_staged_evidence_is_mixed_with_product_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            for path in ("package.json", "governance/audits/reliability_release_gate.json"):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x\n", encoding="utf-8")
            _git(root, "add", "package.json", "governance/audits/reliability_release_gate.json")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_review_boundary.py"),
                    "--root",
                    str(root),
                    "--strict",
                    "--json",
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["mixed_staged_evidence"])

    def test_strict_passes_when_only_evidence_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            target = root / "governance/audits/reliability_release_gate.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x\n", encoding="utf-8")
            _git(root, "add", "governance/audits/reliability_release_gate.json")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/check_review_boundary.py"),
                    "--root",
                    str(root),
                    "--strict",
                    "--json",
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["mixed_staged_evidence"])


if __name__ == "__main__":
    unittest.main()
