from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agora.audit_daemon import AuditDaemon, sign_request
from agora.state_projector import StateProjector


class StateProjectorTests(unittest.TestCase):
    def _prepare_audit(self, td: str) -> Path:
        daemon = AuditDaemon(
            audit_log_path=Path(td) / "sessions" / "s1" / "audit.jsonl",
            wal_dir=Path(td) / "audit" / "wal",
            key_store={"orchestrator": {"key_v1": "secret-abc"}},
        )
        for i in range(1, 4):
            req = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id=f"evt-{i}",
                event_type="route_decision",
                payload={"idx": i},
                timestamp=datetime.now(timezone.utc),
            )
            daemon.append_event(req)
        return Path(td) / "sessions" / "s1" / "audit.jsonl"

    def test_project_and_consistency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = self._prepare_audit(td)
            sqlite_path = Path(td) / "indexes" / "state.db"

            projector = StateProjector(audit, sqlite_path)
            inserted = projector.project_once()
            self.assertEqual(inserted, 3)

            c = projector.consistency_check()
            self.assertTrue(c.consistent)
            self.assertEqual(c.projected_count, 3)

    def test_detect_and_rebuild_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = self._prepare_audit(td)
            sqlite_path = Path(td) / "indexes" / "state.db"

            projector = StateProjector(audit, sqlite_path)
            projector.project_once()

            # mutate audit log to create mismatch
            with audit.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "event_id": "evt-extra",
                            "seq_no": 99,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "component_id": "orchestrator",
                            "event_type": "extra",
                            "payload": {"k": "v"},
                            "trace_id": "trace-extra",
                        }
                    )
                    + "\n"
                )

            c1 = projector.consistency_check()
            self.assertFalse(c1.consistent)

            rebuilt = projector.rebuild_index()
            self.assertEqual(rebuilt, 4)
            c2 = projector.consistency_check()
            self.assertTrue(c2.consistent)

    def test_single_writer_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit = self._prepare_audit(td)
            sqlite_path = Path(td) / "indexes" / "state.db"

            projector = StateProjector(
                audit,
                sqlite_path,
                writer_id="not_projector_uid",
                authorized_writer_id="projector_uid",
            )
            with self.assertRaises(PermissionError):
                projector.project_once()


if __name__ == "__main__":
    unittest.main()
