from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConsistencyResult:
    consistent: bool
    projected_count: int
    audit_line_count: int
    reason: str


class StateProjector:
    """Single-writer projection from append-only audit log to SQLite index."""

    def __init__(
        self,
        audit_log_path: str | Path,
        sqlite_path: str | Path,
        writer_id: str = "projector_uid",
        authorized_writer_id: str = "projector_uid",
    ) -> None:
        self.audit_log_path = Path(audit_log_path)
        self.sqlite_path = Path(sqlite_path)
        self.writer_id = writer_id
        self.authorized_writer_id = authorized_writer_id

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_db()

    def _ensure_db(self) -> None:
        with closing(sqlite3.connect(self.sqlite_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    seq_no INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    component_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projector_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def project_once(self) -> int:
        self._assert_single_writer()
        inserted = 0
        if not self.audit_log_path.exists():
            return inserted

        with closing(sqlite3.connect(self.sqlite_path)) as conn:
            for line in self.audit_log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO audit_events
                    (event_id, seq_no, timestamp, component_id, event_type, trace_id, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["event_id"],
                        int(row["seq_no"]),
                        row["timestamp"],
                        row["component_id"],
                        row["event_type"],
                        row.get("trace_id", "trace-unknown"),
                        json.dumps(row.get("payload", {}), sort_keys=True),
                    ),
                )
                if cur.rowcount == 1:
                    inserted += 1

            self._store_meta(conn)
            conn.commit()

        return inserted

    def consistency_check(self) -> ConsistencyResult:
        audit_line_count = self._audit_line_count()
        audit_hash = self._audit_hash()

        with closing(sqlite3.connect(self.sqlite_path)) as conn:
            projected_count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
            row_hash = conn.execute(
                "SELECT value FROM projector_meta WHERE key='audit_hash'"
            ).fetchone()
            row_count = conn.execute(
                "SELECT value FROM projector_meta WHERE key='audit_line_count'"
            ).fetchone()

        if row_hash is None or row_count is None:
            return ConsistencyResult(
                consistent=False,
                projected_count=projected_count,
                audit_line_count=audit_line_count,
                reason="missing_meta",
            )

        meta_hash = row_hash[0]
        meta_count = int(row_count[0])

        if meta_hash != audit_hash or meta_count != audit_line_count:
            return ConsistencyResult(
                consistent=False,
                projected_count=projected_count,
                audit_line_count=audit_line_count,
                reason="hash_or_count_mismatch",
            )

        if projected_count != audit_line_count:
            return ConsistencyResult(
                consistent=False,
                projected_count=projected_count,
                audit_line_count=audit_line_count,
                reason="projected_count_mismatch",
            )

        return ConsistencyResult(
            consistent=True,
            projected_count=projected_count,
            audit_line_count=audit_line_count,
            reason="ok",
        )

    def rebuild_index(self) -> int:
        self._assert_single_writer()
        with closing(sqlite3.connect(self.sqlite_path)) as conn:
            conn.execute("DELETE FROM audit_events")
            conn.execute("DELETE FROM projector_meta")
            conn.commit()
        return self.project_once()

    def _store_meta(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO projector_meta(key,value) VALUES('audit_hash', ?)",
            (self._audit_hash(),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO projector_meta(key,value) VALUES('audit_line_count', ?)",
            (str(self._audit_line_count()),),
        )

    def _assert_single_writer(self) -> None:
        if self.writer_id != self.authorized_writer_id:
            raise PermissionError(
                f"state projector write denied for writer_id={self.writer_id!r}; "
                f"authorized={self.authorized_writer_id!r}"
            )

    def _audit_hash(self) -> str:
        if not self.audit_log_path.exists():
            return ""
        raw = self.audit_log_path.read_bytes()
        return hashlib.sha256(raw).hexdigest()

    def _audit_line_count(self) -> int:
        if not self.audit_log_path.exists():
            return 0
        return sum(1 for line in self.audit_log_path.read_text(encoding="utf-8").splitlines() if line.strip())
