from __future__ import annotations

import json
import unittest
from pathlib import Path

from policy.hard_constraints import check_hard_constraints


class HardConstraintAdversarialTests(unittest.TestCase):
    def test_adversarial_fixture_accuracy(self) -> None:
        fixture = Path("tests/fixtures/hard_constraint_adversarial.jsonl")
        rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreaterEqual(len(rows), 20)

        total = 0
        passed = 0
        false_positive = 0
        blocked_rows = 0

        for row in rows:
            total += 1
            expected = bool(row["expected_blocked"])
            result = check_hard_constraints(str(row["input"]))
            actual = bool(result.hit)
            if actual == expected:
                passed += 1
            if expected and actual:
                blocked_rows += 1
                self.assertIn(result.constraint_match_path, {"semantic", "regex", "keyword"})
            if not expected and actual:
                false_positive += 1

        accuracy = passed / total
        self.assertGreaterEqual(accuracy, 0.95)
        self.assertEqual(false_positive, 0)
        self.assertGreater(blocked_rows, 0)


if __name__ == "__main__":
    unittest.main()
