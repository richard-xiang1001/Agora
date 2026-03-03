from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class RuntimeStabilityBenchmarkTests(unittest.TestCase):
    def test_runtime_stability_benchmark_and_lint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "runtime_stability.json"
            baseline = Path(td) / "baseline.json"
            lint_out = Path(td) / "runtime_stability_lint.json"

            proc = subprocess.run(
                ["python3", "scripts/benchmark_runtime_stability.py", "--out", str(out), "--samples", "8"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)

            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("p95_latency_ms", data)
            self.assertIn("error_rate", data)
            self.assertIn("cancel_latency_ms_p95", data)

            baseline.write_text(
                json.dumps(
                    {
                        "p95_latency_ms": float(data["p95_latency_ms"]) * 2.0,
                        "error_rate": float(data["error_rate"]) + 0.1,
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    "python3",
                    "scripts/lint_runtime_stability_benchmark.py",
                    "--path",
                    str(out),
                    "--baseline",
                    str(baseline),
                    "--out",
                    str(lint_out),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)
            lint = json.loads(lint_out.read_text(encoding="utf-8"))
            self.assertTrue(lint["pass"])


if __name__ == "__main__":
    unittest.main()
