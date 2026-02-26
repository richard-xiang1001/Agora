from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agora.audit_daemon import AuditDaemon, sign_request


class AuditDaemonTests(unittest.TestCase):
    def _make_daemon(self, td: str, wal_mb: int = 1) -> AuditDaemon:
        return AuditDaemon(
            audit_log_path=Path(td) / "sessions" / "s1" / "audit.jsonl",
            wal_dir=Path(td) / "audit" / "wal",
            key_store={"orchestrator": {"key_v1": "secret-abc"}},
            wal_capacity_mb=wal_mb,
        )

    def test_hmac_verified_append(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = self._make_daemon(td)
            req = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id="evt-001",
                event_type="route_decision",
                payload={"route": "code_review"},
                timestamp=datetime.now(timezone.utc),
            )
            result = daemon.append_event(req)
            self.assertTrue(result.accepted)
            self.assertFalse(result.wrote_to_wal)
            self.assertEqual(result.seq_no, 1)

    def test_invalid_hmac_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = self._make_daemon(td)
            req = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="wrong-secret",
                event_id="evt-001",
                event_type="route_decision",
                payload={"route": "code_review"},
                timestamp=datetime.now(timezone.utc),
            )
            with self.assertRaises(PermissionError):
                daemon.append_event(req)

    def test_deduplicate_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = self._make_daemon(td)
            req = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id="evt-dup",
                event_type="route_decision",
                payload={"route": "unknown"},
                timestamp=datetime.now(timezone.utc),
            )
            r1 = daemon.append_event(req)
            r2 = daemon.append_event(req)
            self.assertFalse(r1.duplicate)
            self.assertTrue(r2.duplicate)

    def test_wal_replay_and_readonly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = self._make_daemon(td, wal_mb=1)
            req1 = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id="evt-wal-1",
                event_type="debate_round",
                payload={"n": 1},
                timestamp=datetime.now(timezone.utc),
            )
            req2 = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id="evt-wal-2",
                event_type="debate_round",
                payload={"n": 2},
                timestamp=datetime.now(timezone.utc),
            )

            daemon.append_event(req1, force_wal=True)
            daemon.append_event(req2, force_wal=True)
            self.assertFalse(daemon.wal_replay_complete())

            replayed = daemon.replay_wal_once()
            self.assertEqual(replayed, 2)
            self.assertTrue(daemon.wal_replay_complete())

            log = Path(td) / "sessions" / "s1" / "audit.jsonl"
            rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["seq_no"], 1)
            self.assertEqual(rows[1]["seq_no"], 2)

    def test_readonly_mode_on_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            daemon = self._make_daemon(td, wal_mb=0)
            req = sign_request(
                component_id="orchestrator",
                key_id="key_v1",
                secret="secret-abc",
                event_id="evt-wal-big",
                event_type="big",
                payload={"blob": "x" * 8192},
                timestamp=datetime.now(timezone.utc),
            )
            daemon.append_event(req, force_wal=True)
            self.assertTrue(daemon.is_readonly_mode())


if __name__ == "__main__":
    unittest.main()
