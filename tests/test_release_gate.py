from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import yaml

from agora.release_gate import apply_overdue_escalation, evaluate_release


class ReleaseGateTests(unittest.TestCase):
    def test_hard_constraint_failure_blocks(self) -> None:
        results = [
            {
                "category": "hard_constraint",
                "pass_rate": 0.99,
            }
        ]
        d = evaluate_release(results, {"hard_constraint": 1.0})
        self.assertTrue(d.blocked)

    def test_soft_failure_creates_incident_stub(self) -> None:
        results = [
            {
                "category": "injection_medium",
                "pass_rate": 0.90,
            }
        ]
        d = evaluate_release(results, {"injection_medium": 0.95})
        self.assertFalse(d.blocked)
        self.assertEqual(len(d.incidents_to_create), 1)

    def test_overdue_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "AGR-999.yaml"
            p.write_text(
                yaml.safe_dump(
                    {
                        "incident_id": "AGR-999",
                        "test_category": "injection",
                        "status": "open",
                        "due_date": (date.today() - timedelta(days=1)).isoformat(),
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            base = {"injection_high": 0.95, "injection_medium": 0.95}
            out = apply_overdue_escalation(thresholds=base, incidents_dir=td)
            self.assertEqual(out["injection_high"], 1.0)
            self.assertEqual(out["injection_medium"], 1.0)


if __name__ == "__main__":
    unittest.main()
