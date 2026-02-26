from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.lint_failure_report import lint_report


class FailureReportLintTests(unittest.TestCase):
    def test_failure_report_passes_with_schema(self) -> None:
        schema = yaml.safe_load(
            Path("/Users/xiangruichao/Desktop/Agora/governance/failure_report_schema.yaml").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as td:
            report_path = Path(td) / "failure.yaml"
            report_path.write_text(
                yaml.safe_dump(
                    {
                        "failure_id": "AGR-999",
                        "component": "router",
                        "trigger": "bad enum",
                        "observed": "fallback to unknown",
                        "expected": "route to code_review",
                        "root_cause": "feature output invalid enum",
                        "next_week_action": "add strict enum mapping for task_intent",
                        "severity": "medium",
                        "test_category": "fallback",
                        "date": "2026-02-26",
                    },
                    sort_keys=False,
                    allow_unicode=False,
                ),
                encoding="utf-8",
            )
            errs = lint_report(schema, report_path)
            self.assertEqual(errs, [])


if __name__ == "__main__":
    unittest.main()
