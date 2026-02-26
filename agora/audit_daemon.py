from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from agora.models import AuditAppendRequest, AuditEvent


@dataclass(frozen=True)
class AuditAppendResult:
    accepted: bool
    duplicate: bool
    seq_no: int | None
    wrote_to_wal: bool


class AuditDaemon:
    """Week 4 audit engine: HMAC verification, seq allocation, WAL buffering and replay."""

    def __init__(
        self,
        audit_log_path: str | Path,
        wal_dir: str | Path,
        key_store: dict[str, dict[str, str]],
        wal_capacity_mb: int = 512,
    ) -> None:
        self.audit_log_path = Path(audit_log_path)
        self.wal_dir = Path(wal_dir)
        self.key_store = key_store
        self.wal_capacity_bytes = wal_capacity_mb * 1024 * 1024

        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        self._seq_file = self.wal_dir / ".seq"
        self._seq_lock = Lock()
        self._event_ids: set[str] = set()
        self._load_existing_event_ids()

    def append_event(self, request: AuditAppendRequest, force_wal: bool = False) -> AuditAppendResult:
        self._verify_hmac(request)

        if request.event_id in self._event_ids:
            return AuditAppendResult(
                accepted=True,
                duplicate=True,
                seq_no=None,
                wrote_to_wal=False,
            )

        seq_no = self._next_seq_no()
        event = AuditEvent(
            event_id=request.event_id,
            seq_no=seq_no,
            timestamp=request.timestamp,
            component_id=request.component_id,
            event_type=request.event_type,
            payload=request.payload,
            trace_id=request.trace_id,
        )

        if force_wal:
            self._append_wal(event)
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=True,
            )

        try:
            self._append_audit(event)
            self._event_ids.add(event.event_id)
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=False,
            )
        except OSError:
            self._append_wal(event)
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=True,
            )

    def is_readonly_mode(self) -> bool:
        return self._wal_size_bytes() >= self.wal_capacity_bytes

    def replay_wal_once(self) -> int:
        """Replay WAL events back to audit log. Returns replayed count."""

        replayed = 0
        for path in sorted(self.wal_dir.glob("*.jsonl")):
            remaining: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                event_id = row["event_id"]
                if event_id in self._event_ids:
                    continue
                row = _coerce_audit_row(row)
                event = AuditEvent(**row)
                try:
                    self._append_audit(event)
                    self._event_ids.add(event.event_id)
                    replayed += 1
                except OSError:
                    remaining.append(line)

            if remaining:
                path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
            else:
                path.unlink(missing_ok=True)

        return replayed

    def wal_replay_complete(self) -> bool:
        pending = self.pending_wal_event_ids()
        if not pending:
            return True
        return all(event_id in self._event_ids for event_id in pending)

    def pending_wal_event_ids(self) -> set[str]:
        out: set[str] = set()
        for path in self.wal_dir.glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                out.add(row["event_id"])
        return out

    def _verify_hmac(self, request: AuditAppendRequest) -> None:
        component_keys = self.key_store.get(request.component_id)
        if not component_keys:
            raise PermissionError(f"unknown component_id: {request.component_id}")

        secret = component_keys.get(request.key_id)
        if not secret:
            raise PermissionError(
                f"unknown key_id {request.key_id!r} for component {request.component_id!r}"
            )

        canonical = canonical_payload(
            component_id=request.component_id,
            key_id=request.key_id,
            event_id=request.event_id,
            event_type=request.event_type,
            payload=request.payload,
            trace_id=request.trace_id,
            timestamp=request.timestamp,
        )
        expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.hmac_sig):
            raise PermissionError("invalid hmac signature")

    def _append_audit(self, event: AuditEvent) -> None:
        row = json.dumps(event.model_dump(mode="json"), ensure_ascii=True)
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(row + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _append_wal(self, event: AuditEvent) -> None:
        segment = self.wal_dir / f"wal-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.jsonl"
        row = json.dumps(event.model_dump(mode="json"), ensure_ascii=True)
        with segment.open("a", encoding="utf-8") as f:
            f.write(row + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _next_seq_no(self) -> int:
        with self._seq_lock:
            if self._seq_file.exists():
                current = int(self._seq_file.read_text(encoding="utf-8").strip() or "0")
            else:
                current = 0
            nxt = current + 1
            self._seq_file.write_text(str(nxt), encoding="utf-8")
            return nxt

    def _load_existing_event_ids(self) -> None:
        if not self.audit_log_path.exists():
            return
        for line in self.audit_log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = row.get("event_id")
            if isinstance(event_id, str):
                self._event_ids.add(event_id)

    def _wal_size_bytes(self) -> int:
        total = 0
        for path in self.wal_dir.glob("*.jsonl"):
            total += path.stat().st_size
        return total


def canonical_payload(
    *,
    component_id: str,
    key_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    trace_id: str,
    timestamp: datetime,
) -> bytes:
    body = {
        "component_id": component_id,
        "key_id": key_id,
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "trace_id": trace_id,
        "timestamp": timestamp.isoformat(),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_request(
    *,
    component_id: str,
    key_id: str,
    secret: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    trace_id: str = "trace-local",
    timestamp: datetime | None = None,
) -> AuditAppendRequest:
    timestamp = timestamp or datetime.now(timezone.utc)
    canonical = canonical_payload(
        component_id=component_id,
        key_id=key_id,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
        timestamp=timestamp,
    )
    sig = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return AuditAppendRequest(
        component_id=component_id,
        key_id=key_id,
        hmac_sig=sig,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
        timestamp=timestamp,
    )


def _coerce_audit_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    ts = out.get("timestamp")
    if isinstance(ts, str):
        # Accept both RFC3339 Z suffix and +00:00 offsets.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        out["timestamp"] = datetime.fromisoformat(ts)
    return out
