from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agora.sandbox_gc import SandboxGC


class SandboxGCTests(unittest.TestCase):
    def _write_manifest(self, root: Path, wf: str, status: str, minutes_ago: int) -> None:
        d = root / wf
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        payload = {
            "workflow_id": wf,
            "status": status,
            "started_at": ts.isoformat(),
            "last_heartbeat": ts.isoformat(),
        }
        (d / "sandbox_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def test_gc_skips_active_and_removes_expired_non_active(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write_manifest(root, "wf-active", "active", minutes_ago=120)
            self._write_manifest(root, "wf-completed-old", "completed", minutes_ago=120)
            self._write_manifest(root, "wf-failed-fresh", "failed", minutes_ago=5)

            gc = SandboxGC(root, ttl_minutes=30)
            result = gc.run_once()

            self.assertEqual(result.scanned, 3)
            self.assertEqual(result.skipped_active, 1)
            self.assertEqual(result.removed, 1)
            self.assertTrue((root / "wf-active").exists())
            self.assertFalse((root / "wf-completed-old").exists())
            self.assertTrue((root / "wf-failed-fresh").exists())


if __name__ == "__main__":
    unittest.main()
