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
    durability_mode: str = "audit"
    audit_state: str = "normal"
    health_snapshot: dict[str, Any] | None = None


class AuditDaemon:
    """Week 4 audit engine: HMAC verification, seq allocation, WAL buffering and replay."""

    def __init__(
        self,
        audit_log_path: str | Path,
        wal_dir: str | Path,
        key_store: dict[str, dict[str, str]],
        wal_capacity_mb: int = 512,
        recovery_cooldown_seconds: int = 120,
        degraded_max_seconds: int = 300,
        degraded_max_requests: int = 50,
        scrub_policy: dict[str, Any] | None = None,
    ) -> None:
        self.audit_log_path = Path(audit_log_path)
        self.wal_dir = Path(wal_dir)
        self.key_store = key_store
        self.wal_capacity_bytes = wal_capacity_mb * 1024 * 1024
        self.recovery_cooldown_seconds = recovery_cooldown_seconds
        self.degraded_max_seconds = degraded_max_seconds
        self.degraded_max_requests = degraded_max_requests
        self.scrub_policy = self._normalize_scrub_policy(scrub_policy)

        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_dir.mkdir(parents=True, exist_ok=True)
        self._seq_file = self.wal_dir / ".seq"
        self._health_state_file = self.wal_dir.parent / "health_state.json"
        self._seq_lock = Lock()
        self._health_lock = Lock()
        self._event_ids: set[str] = set()
        self._load_existing_event_ids()
        self.refresh_health_state(cause="init")

    def append_event(self, request: AuditAppendRequest, force_wal: bool = False) -> AuditAppendResult:
        self.refresh_health_state(cause="append_pre")
        self._verify_hmac(request)

        if request.event_id in self._event_ids:
            state = self.refresh_health_state(cause="append_duplicate")
            return AuditAppendResult(
                accepted=True,
                duplicate=True,
                seq_no=None,
                wrote_to_wal=False,
                durability_mode="audit",
                audit_state=state["audit_state"],
                health_snapshot=self._build_health_snapshot(state),
            )

        seq_no = self._next_seq_no()
        scrubbed_payload = self._scrub_payload(request.payload)
        event = AuditEvent(
            event_id=request.event_id,
            seq_no=seq_no,
            timestamp=request.timestamp,
            component_id=request.component_id,
            event_type=request.event_type,
            payload=scrubbed_payload,
            trace_id=request.trace_id,
        )

        if force_wal:
            self._append_wal(event)
            state = self.refresh_health_state(cause="append", increment_degraded=True)
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=True,
                durability_mode="wal",
                audit_state=state["audit_state"],
                health_snapshot=self._build_health_snapshot(state),
            )

        try:
            self._append_audit(event)
            self._event_ids.add(event.event_id)
            state = self.refresh_health_state(cause="append")
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=False,
                durability_mode="audit",
                audit_state=state["audit_state"],
                health_snapshot=self._build_health_snapshot(state),
            )
        except OSError:
            self._append_wal(event)
            state = self.refresh_health_state(cause="append", increment_degraded=True)
            return AuditAppendResult(
                accepted=True,
                duplicate=False,
                seq_no=seq_no,
                wrote_to_wal=True,
                durability_mode="wal",
                audit_state=state["audit_state"],
                health_snapshot=self._build_health_snapshot(state),
            )

    def is_readonly_mode(self) -> bool:
        return self._wal_size_bytes() >= self.wal_capacity_bytes

    def replay_wal_once(self) -> int:
        """Replay WAL events back to audit log. Returns replayed count."""

        self.refresh_health_state(cause="replay_pre")
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

        self.refresh_health_state(cause="replay_post")
        return replayed

    def get_health_snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        state = self.refresh_health_state(now=now, cause="read")
        return self._build_health_snapshot(state, now=now)

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

    @staticmethod
    def _normalize_scrub_policy(raw: dict[str, Any] | None) -> dict[str, Any]:
        default = {
            "enabled": True,
            "max_chars_per_field": {"diff": 500, "error_message": 300, "stderr_tail": 400},
            "scrub_marker": "[scrubbed:{original_len}]",
            "scrubbed_event_field": "scrubbed_fields",
        }
        if not isinstance(raw, dict):
            return default
        cfg = raw.get("scrub", raw)
        if not isinstance(cfg, dict):
            return default
        max_chars = cfg.get("max_chars_per_field", {})
        clean_max_chars: dict[str, int] = {}
        if isinstance(max_chars, dict):
            for key, value in max_chars.items():
                if not isinstance(key, str):
                    continue
                try:
                    n = int(value)
                except Exception:  # noqa: BLE001
                    continue
                if n > 0:
                    clean_max_chars[key] = n
        if not clean_max_chars:
            clean_max_chars = default["max_chars_per_field"]
        marker = cfg.get("scrub_marker", default["scrub_marker"])
        marker = marker if isinstance(marker, str) and marker else default["scrub_marker"]
        scrubbed_event_field = cfg.get("scrubbed_event_field", default["scrubbed_event_field"])
        scrubbed_event_field = (
            scrubbed_event_field
            if isinstance(scrubbed_event_field, str) and scrubbed_event_field
            else default["scrubbed_event_field"]
        )
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "max_chars_per_field": clean_max_chars,
            "scrub_marker": marker,
            "scrubbed_event_field": scrubbed_event_field,
        }

    def _scrub_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        if not bool(self.scrub_policy.get("enabled", True)):
            return payload
        out = dict(payload)
        scrubbed_fields: list[str] = []
        marker_tpl = str(self.scrub_policy.get("scrub_marker", "[scrubbed:{original_len}]"))
        for field, max_chars in dict(self.scrub_policy.get("max_chars_per_field", {})).items():
            value = out.get(field)
            if not isinstance(value, str):
                continue
            limit = int(max_chars)
            if limit <= 0 or len(value) <= limit:
                continue
            marker = marker_tpl.format(original_len=len(value))
            out[field] = value[:limit] + marker
            scrubbed_fields.append(field)
        if scrubbed_fields:
            field_name = str(self.scrub_policy.get("scrubbed_event_field", "scrubbed_fields"))
            out[field_name] = sorted(set(scrubbed_fields))
            out["scrub_triggered"] = True
        return out

    def _wal_size_bytes(self) -> int:
        total = 0
        for path in self.wal_dir.glob("*.jsonl"):
            total += path.stat().st_size
        return total

    def refresh_health_state(
        self,
        now: datetime | None = None,
        cause: str = "read",
        increment_degraded: bool = False,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        with self._health_lock:
            state = self._load_health_state_or_init()

            pending = len(self.pending_wal_event_ids())
            wal_bytes = self._wal_size_bytes()
            state["pending_wal_events"] = pending
            state["wal_size_bytes"] = wal_bytes

            mode = self._compute_runtime_audit_mode(pending, wal_bytes)
            prev_mode = state.get("audit_state")
            state["audit_state"] = mode

            if mode in {"degraded", "readonly"}:
                if state.get("degraded_since") is None:
                    state["degraded_since"] = now.isoformat()
                state["normal_since"] = None
                if increment_degraded and mode == "degraded":
                    state["degraded_request_count"] = int(state.get("degraded_request_count", 0)) + 1
            else:
                if prev_mode != "normal" or state.get("normal_since") is None:
                    state["normal_since"] = now.isoformat()

                if self._is_recovered(now, state):
                    state["degraded_since"] = None
                    state["degraded_request_count"] = 0

            state["last_updated"] = now.isoformat()
            state["last_refresh_cause"] = cause
            self._write_health_state(state)
            return state

    def _compute_runtime_audit_mode(self, pending_wal_events: int, wal_size_bytes: int) -> str:
        if wal_size_bytes >= self.wal_capacity_bytes:
            return "readonly"
        if pending_wal_events > 0 or wal_size_bytes > 0:
            return "degraded"
        return "normal"

    def _is_recovered(self, now: datetime, state: dict[str, Any]) -> bool:
        if state.get("audit_state") != "normal":
            return False
        normal_since = _parse_optional_dt(state.get("normal_since"))
        if normal_since is None:
            return False
        if (now - normal_since).total_seconds() < float(state.get("recovery_cooldown_seconds", 0)):
            return False
        if int(state.get("pending_wal_events", 0)) != 0:
            return False
        if int(state.get("wal_size_bytes", 0)) != 0:
            return False
        return True

    def _build_health_snapshot(
        self, state: dict[str, Any], now: datetime | None = None
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        degraded_since = _parse_optional_dt(state.get("degraded_since"))
        normal_since = _parse_optional_dt(state.get("normal_since"))

        degraded_seconds = (
            int((now - degraded_since).total_seconds()) if degraded_since is not None else 0
        )
        normal_seconds = int((now - normal_since).total_seconds()) if normal_since is not None else 0
        degraded_request_count = int(state.get("degraded_request_count", 0))
        budget_exceeded = (
            degraded_seconds >= self.degraded_max_seconds
            or degraded_request_count >= self.degraded_max_requests
        )

        return {
            "audit_state": state.get("audit_state", "normal"),
            "degraded_since": state.get("degraded_since"),
            "normal_since": state.get("normal_since"),
            "degraded_seconds": degraded_seconds,
            "normal_seconds": normal_seconds,
            "degraded_request_count": degraded_request_count,
            "pending_wal_events": int(state.get("pending_wal_events", 0)),
            "wal_size_bytes": int(state.get("wal_size_bytes", 0)),
            "recovery_cooldown_seconds": int(
                state.get("recovery_cooldown_seconds", self.recovery_cooldown_seconds)
            ),
            "budget_exceeded": budget_exceeded,
            "last_updated": state.get("last_updated"),
            "last_refresh_cause": state.get("last_refresh_cause", "unknown"),
        }

    def _load_health_state_or_init(self) -> dict[str, Any]:
        if not self._health_state_file.exists():
            return {
                "schema_version": 1,
                "audit_state": "normal",
                "degraded_since": None,
                "normal_since": datetime.now(timezone.utc).isoformat(),
                "degraded_request_count": 0,
                "pending_wal_events": 0,
                "wal_size_bytes": 0,
                "recovery_cooldown_seconds": self.recovery_cooldown_seconds,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "last_refresh_cause": "init",
            }

        raw = json.loads(self._health_state_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("invalid health_state.json payload")
        raw.setdefault("schema_version", 1)
        raw.setdefault("audit_state", "normal")
        raw.setdefault("degraded_since", None)
        raw.setdefault("normal_since", None)
        raw.setdefault("degraded_request_count", 0)
        raw.setdefault("pending_wal_events", 0)
        raw.setdefault("wal_size_bytes", 0)
        raw.setdefault("recovery_cooldown_seconds", self.recovery_cooldown_seconds)
        raw.setdefault("last_updated", datetime.now(timezone.utc).isoformat())
        raw.setdefault("last_refresh_cause", "load")
        return raw

    def _write_health_state(self, state: dict[str, Any]) -> None:
        tmp = self._health_state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp.replace(self._health_state_file)


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


def _parse_optional_dt(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    ts = value
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)
