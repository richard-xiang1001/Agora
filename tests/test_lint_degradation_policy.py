from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


class LintDegradationPolicyTests(unittest.TestCase):
    def _run(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/lint_degradation_policy.py", "--file", str(path)],
            capture_output=True,
            text=True,
        )

    def test_current_policy_passes(self) -> None:
        p = self._run(Path("config/audit_degradation_policy.yaml"))
        self.assertEqual(p.returncode, 0, msg=p.stdout + p.stderr)

    def test_missing_required_field_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.yaml"
            p.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "max_degraded_seconds": 300,
                        # max_degraded_requests missing
                        "allow_during_degraded": {
                            "risk_levels": ["low"],
                            "routes": ["unknown_workflow"],
                            "requires_tools": False,
                        },
                        "on_budget_exceeded": "block_all_messages",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            out = self._run(p)
            self.assertNotEqual(out.returncode, 0, msg=out.stdout + out.stderr)

    def test_invalid_on_budget_exceeded_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad_enum.yaml"
            p.write_text(
                yaml.safe_dump(
                    {
                        "version": "v1",
                        "max_degraded_seconds": 300,
                        "max_degraded_requests": 50,
                        "allow_during_degraded": {
                            "risk_levels": ["low"],
                            "routes": ["unknown_workflow"],
                            "requires_tools": False,
                        },
                        "on_budget_exceeded": "drop_everything",
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            out = self._run(p)
            self.assertNotEqual(out.returncode, 0, msg=out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
