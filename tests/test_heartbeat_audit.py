from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agora.audit_daemon import AuditDaemon
from agora.heartbeat import HeartbeatScheduler


class HeartbeatAuditTests(unittest.TestCase):
    def test_heartbeat_writes_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "heartbeat.yaml"
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
            daemon = AuditDaemon(
                audit_log_path=root / "audit" / "audit.jsonl",
                wal_dir=root / "audit" / "wal",
                key_store={"gateway": {"key_v1": "dev-secret-gateway"}},
            )
            hb = HeartbeatScheduler(cfg)
            result = hb.run_once(
                requested_operations=["mark_stale_decisions", "tool_execute"],
                output_dir=root,
                audit_append=daemon.append_event,
                component_id="gateway",
                key_id="key_v1",
                secret="dev-secret-gateway",
                trace_id="trace-hb-test",
            )
            self.assertTrue(Path(result.report_path).exists())

            rows = [
                json.loads(x)
                for x in (root / "audit" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
                if x.strip()
            ]
            self.assertGreaterEqual(len(rows), 1)
            evt = rows[-1]
            self.assertEqual(evt["event_type"], "heartbeat_run")
            self.assertIn("event_id", evt)
            self.assertIn("seq_no", evt)


if __name__ == "__main__":
    unittest.main()
