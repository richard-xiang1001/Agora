from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agora.release_gate import normalize_test_category
from scripts.lint_failure_report import lint_report


class ReleaseGateMetadataQualityTests(unittest.TestCase):
    def _schema(self) -> dict:
        return yaml.safe_load(Path("governance/failure_report_schema.yaml").read_text(encoding="utf-8"))

    def _base_report(self) -> dict:
        return {
            "failure_id": "AGR-998",
            "component": "governance",
            "trigger": "metadata quality test",
            "observed": "n/a",
            "expected": "n/a",
            "root_cause": "n/a",
            "next_week_action": "add explicit metadata validation for release gate incident categories",
            "severity": "medium",
            "test_category": "audit_integrity",
            "date": "2026-02-28",
        }

    def _lint(self, payload: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fr.yaml"
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            return lint_report(self._schema(), path)

    def test_missing_test_category_fails(self) -> None:
        payload = self._base_report()
        payload.pop("test_category")
        errs = self._lint(payload)
        self.assertTrue(any("test_category" in e for e in errs))

    def test_invalid_test_category_fails(self) -> None:
        payload = self._base_report()
        payload["test_category"] = "bad_category"
        errs = self._lint(payload)
        self.assertTrue(any("test_category must be one of" in e or "must be one of" in e for e in errs))

    def test_empty_test_category_detail_fails(self) -> None:
        payload = self._base_report()
        payload["test_category_detail"] = ""
        errs = self._lint(payload)
        self.assertTrue(any("test_category_detail" in e for e in errs))

    def test_normalize_category_coverage(self) -> None:
        self.assertEqual(normalize_test_category("injection_high"), "injection")
        self.assertEqual(normalize_test_category("injection_medium"), "injection")
        self.assertEqual(normalize_test_category("fault_storm"), "fallback")
        self.assertEqual(normalize_test_category("hard_constraint"), "hard_constraint")


if __name__ == "__main__":
    unittest.main()
