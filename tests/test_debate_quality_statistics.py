from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class DebateQualityStatisticsTests(unittest.TestCase):
    def test_quality_benchmark_contains_statistics_and_lint_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "quality_stats.json"
            lint_out = Path(td) / "quality_stats_lint.json"

            proc = subprocess.run(
                ["python3", "scripts/benchmark_debate_quality.py", "--out", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("n_samples", data)
            self.assertIn("p_value", data)
            self.assertIn("effect_size", data)
            self.assertGreaterEqual(int(data["n_samples"]), 20)

            proc = subprocess.run(
                [
                    "python3",
                    "scripts/lint_debate_quality_benchmark.py",
                    "--path",
                    str(out),
                    "--out",
                    str(lint_out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)
            lint = json.loads(lint_out.read_text(encoding="utf-8"))
            self.assertTrue(lint["quality_pass"])
            self.assertEqual(lint["error_count"], 0)


if __name__ == "__main__":
    unittest.main()
