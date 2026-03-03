from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAYER_NAMES = ("episodic", "semantic", "procedural")


class MemoryLayerStore:
    def __init__(self, root: Path, session_id: str) -> None:
        self.root = root
        self.session_id = session_id
        self.base = root / "sessions" / session_id / "memory_v2"
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, layer: str) -> Path:
        return self.base / f"{layer}.jsonl"

    def _rows(self, layer: str) -> list[dict[str, Any]]:
        p = self._path(layer)
        if not p.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        return out

    def _write(self, layer: str, rows: list[dict[str, Any]]) -> None:
        p = self._path(layer)
        tmp = p.with_suffix(".jsonl.tmp")
        payload = "\n".join(json.dumps(x, ensure_ascii=True) for x in rows)
        if payload:
            payload += "\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(p)

    def ingest(self, *, layer: str, content: str, source: str, confidence: float, tags: list[str]) -> tuple[bool, str]:
        rows = self._rows(layer)
        norm = content.strip().lower()
        for row in rows:
            if str(row.get("content", "")).strip().lower() == norm and str(row.get("source", "")) == source:
                return False, str(row.get("record_id"))
        rid = f"mem_{uuid.uuid4().hex[:12]}"
        rows.append(
            {
                "record_id": rid,
                "layer": layer,
                "content": content,
                "source": source,
                "confidence": float(confidence),
                "weight": float(confidence),
                "tags": [str(x) for x in tags],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "decayed": False,
            }
        )
        self._write(layer, rows)
        return True, rid

    def list_all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for layer in LAYER_NAMES:
            out.extend(self._rows(layer))
        return out

    def decay(self) -> int:
        changed = 0
        for layer in LAYER_NAMES:
            rows = self._rows(layer)
            updated = False
            for row in rows:
                w = float(row.get("weight", row.get("confidence", 0.0)))
                nw = round(max(0.0, w * 0.9), 6)
                if nw != w:
                    row["weight"] = nw
                    row["decayed"] = True
                    updated = True
                    changed += 1
            if updated:
                self._write(layer, rows)
        return changed

    def stats(self) -> dict[str, int]:
        by_layer = {layer: len(self._rows(layer)) for layer in LAYER_NAMES}
        by_layer["total"] = sum(by_layer.values())
        return by_layer
