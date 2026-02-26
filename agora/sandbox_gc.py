from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class SandboxGCResult:
    scanned: int
    removed: int
    skipped_active: int


class SandboxGC:
    def __init__(self, base_dir: str | Path, ttl_minutes: int = 30) -> None:
        self.base_dir = Path(base_dir)
        self.ttl = timedelta(minutes=ttl_minutes)

    def run_once(self, now: datetime | None = None) -> SandboxGCResult:
        now = now or datetime.now(timezone.utc)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        scanned = 0
        removed = 0
        skipped_active = 0

        for wf_dir in self.base_dir.iterdir():
            if not wf_dir.is_dir():
                continue
            manifest = wf_dir / "sandbox_manifest.json"
            if not manifest.exists():
                continue

            scanned += 1
            data = json.loads(manifest.read_text(encoding="utf-8"))
            status = data.get("status", "failed")
            if status == "active":
                skipped_active += 1
                continue

            ts_raw = data.get("last_heartbeat") or data.get("started_at")
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                ts = now - self.ttl - timedelta(seconds=1)

            if now - ts > self.ttl:
                shutil.rmtree(wf_dir, ignore_errors=True)
                removed += 1

        return SandboxGCResult(scanned=scanned, removed=removed, skipped_active=skipped_active)
