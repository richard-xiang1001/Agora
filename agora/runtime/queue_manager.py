from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TASK_STATUSES = {"queued", "running", "waiting_user", "cancelled", "completed", "failed"}


@dataclass(frozen=True)
class RuntimeTask:
    task_id: str
    session_id: str
    status: str
    request: dict[str, Any]
    workflow_id: str | None = None
    error: str | None = None
    response: dict[str, Any] | None = None


class QueueManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.runtime_dir = root / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.queue_path = self.runtime_dir / "task_queue.jsonl"

    def _read_rows(self) -> list[dict[str, Any]]:
        if not self.queue_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.queue_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        tmp = self.queue_path.with_suffix(".jsonl.tmp")
        payload = "\n".join(json.dumps(x, ensure_ascii=True) for x in rows)
        if payload:
            payload += "\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.queue_path)

    def enqueue(self, *, session_id: str, request: dict[str, Any]) -> RuntimeTask:
        rows = self._read_rows()
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        row = {
            "task_id": task_id,
            "session_id": session_id,
            "status": "queued",
            "request": request,
            "workflow_id": None,
            "error": None,
            "response": None,
        }
        rows.append(row)
        self._write_rows(rows)
        return RuntimeTask(**row)

    def get(self, task_id: str) -> RuntimeTask | None:
        for row in self._read_rows():
            if row.get("task_id") == task_id:
                return RuntimeTask(**row)
        return None

    def update(self, task_id: str, **updates: Any) -> RuntimeTask | None:
        rows = self._read_rows()
        out: dict[str, Any] | None = None
        for row in rows:
            if row.get("task_id") != task_id:
                continue
            row.update(updates)
            status = str(row.get("status", "queued"))
            if status not in TASK_STATUSES:
                row["status"] = "failed"
            out = row
            break
        self._write_rows(rows)
        if out is None:
            return None
        return RuntimeTask(**out)

    def next_queued(self) -> RuntimeTask | None:
        for row in self._read_rows():
            if row.get("status") == "queued":
                return RuntimeTask(**row)
        return None

    def depth(self) -> int:
        return sum(1 for x in self._read_rows() if x.get("status") in {"queued", "running", "waiting_user"})

    def processed_count(self) -> int:
        return sum(1 for x in self._read_rows() if x.get("status") in {"completed", "failed", "cancelled"})

    def recover_running_to_queued(self) -> int:
        rows = self._read_rows()
        recovered = 0
        for row in rows:
            if row.get("status") == "running":
                row["status"] = "queued"
                recovered += 1
        self._write_rows(rows)
        return recovered
