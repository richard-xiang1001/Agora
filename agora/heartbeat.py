from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from agora.audit_daemon import sign_request
from agora.models import AuditAppendRequest


@dataclass(frozen=True)
class HeartbeatResult:
    allowed: list[str]
    blocked: list[str]
    report_path: str


class HeartbeatScheduler:
    def __init__(self, contract_path: str | Path) -> None:
        payload = yaml.safe_load(Path(contract_path).read_text(encoding="utf-8"))
        self.interval_minutes = int(payload.get("interval_minutes", 15))
        self.allowed_ops = set(payload.get("allowed_operations", []))
        self.denied_ops = set(payload.get("denied_operations", []))

    def run_once(
        self,
        requested_operations: list[str],
        output_dir: str | Path,
        audit_append: Callable[[AuditAppendRequest], object] | None = None,
        component_id: str = "heartbeat",
        key_id: str = "key_v1",
        secret: str | None = None,
        trace_id: str = "trace-heartbeat",
    ) -> HeartbeatResult:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        allowed: list[str] = []
        blocked: list[str] = []
        for op in requested_operations:
            if op in self.denied_ops or op not in self.allowed_ops:
                blocked.append(op)
            else:
                allowed.append(op)

        now = datetime.now(timezone.utc)
        payload = {
            "timestamp": now.isoformat(),
            "interval_minutes": self.interval_minutes,
            "allowed": allowed,
            "blocked": blocked,
        }

        json_path = out_dir / "heartbeat_report.json"
        md_path = out_dir / "heartbeat_report.md"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        allowed_lines = [f"- {x}" for x in allowed] if allowed else ["- (none)"]
        blocked_lines = [f"- {x}" for x in blocked] if blocked else ["- (none)"]
        md = [
            "# Heartbeat Report",
            "",
            f"- timestamp: {payload['timestamp']}",
            f"- interval_minutes: {self.interval_minutes}",
            f"- allowed_count: {len(allowed)}",
            f"- blocked_count: {len(blocked)}",
            "",
            "## Allowed",
            *allowed_lines,
            "",
            "## Blocked",
            *blocked_lines,
            "",
        ]
        md_path.write_text("\n".join(md), encoding="utf-8")

        if audit_append is not None and secret:
            req = sign_request(
                component_id=component_id,
                key_id=key_id,
                secret=secret,
                event_id=f"hb-{int(now.timestamp() * 1000)}",
                event_type="heartbeat_run",
                payload={
                    "allowed": allowed,
                    "blocked": blocked,
                    "report_path": str(md_path),
                },
                trace_id=trace_id,
                timestamp=now,
            )
            audit_append(req)

        return HeartbeatResult(allowed=allowed, blocked=blocked, report_path=str(md_path))
