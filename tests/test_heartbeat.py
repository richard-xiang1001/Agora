from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agora.heartbeat import HeartbeatScheduler


class HeartbeatTests(unittest.TestCase):
    def test_only_whitelisted_ops_are_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "heartbeat.yaml"
            cfg.write_text(
                """
interval_minutes: 15
allowed_operations:
  - mark_stale_decisions
denied_operations:
  - tool_execute
""".strip()
                + "\n",
                encoding="utf-8",
            )
            scheduler = HeartbeatScheduler(cfg)
            result = scheduler.run_once(
                requested_operations=["mark_stale_decisions", "tool_execute", "unknown_op"],
                output_dir=td,
            )
            self.assertEqual(result.allowed, ["mark_stale_decisions"])
            self.assertIn("tool_execute", result.blocked)
            self.assertIn("unknown_op", result.blocked)
            self.assertTrue(Path(result.report_path).exists())


if __name__ == "__main__":
    unittest.main()
