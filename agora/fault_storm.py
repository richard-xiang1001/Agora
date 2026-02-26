from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agora.audit_daemon import AuditDaemon, sign_request
from agora.fallback import FallbackManager


@dataclass(frozen=True)
class FaultStormResult:
    timeout_failover_ok: bool
    wal_readonly_ok: bool
    overall_pass: bool


def run_fault_storm_drill() -> FaultStormResult:
    # Drill 1: primary timeout should switch to fallback model.
    fallback = FallbackManager({"reasoning": ["primary", "backup-1", "backup-2"]}, base_backoff_seconds=1)
    _ = fallback.select_model("reasoning")
    event = fallback.record_failure("reasoning", "timeout")
    timeout_ok = event.switchover_model == "backup-1"

    # Drill 2: WAL forced mode should enter readonly.
    with tempfile.TemporaryDirectory() as td:
        daemon = AuditDaemon(
            audit_log_path=Path(td) / "sessions" / "s1" / "audit.jsonl",
            wal_dir=Path(td) / "audit" / "wal",
            key_store={"orchestrator": {"key_v1": "secret-abc"}},
            wal_capacity_mb=0,
        )
        req = sign_request(
            component_id="orchestrator",
            key_id="key_v1",
            secret="secret-abc",
            event_id="fault-storm-wal-1",
            event_type="fault_storm",
            payload={"simulate": "wal_full"},
            timestamp=datetime.now(timezone.utc),
        )
        daemon.append_event(req, force_wal=True)
        wal_ok = daemon.is_readonly_mode()

    overall = timeout_ok and wal_ok
    return FaultStormResult(timeout_failover_ok=timeout_ok, wal_readonly_ok=wal_ok, overall_pass=overall)
