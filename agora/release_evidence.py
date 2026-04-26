from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_EVIDENCE_SCHEMA_VERSION = "agora_release_evidence_manifest_v1"
DEFAULT_RELEASE_EVIDENCE_PATH = Path("governance/audits/release_evidence_manifest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _git_text(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), text=True, capture_output=True, timeout=10)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def build_release_evidence_manifest(
    *,
    root: Path,
    reliability_gate_path: Path | None = None,
    out: Path | None = None,
    write: bool = True,
    release_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate_path = reliability_gate_path or (root / "governance/audits/reliability_release_gate.json")
    if not gate_path.is_absolute():
        gate_path = root / gate_path
    gate = _read_json(gate_path, {})
    if not isinstance(gate, dict):
        gate = {}
    artifacts = dict(gate.get("artifacts") or {})
    checks = [dict(item) for item in list(gate.get("checks") or []) if isinstance(item, dict)]
    head = _git_text(root, ["rev-parse", "HEAD"])
    status_short = _git_text(root, ["status", "--short"])
    payload = {
        "schema_version": RELEASE_EVIDENCE_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "git": {
            "head": head,
            "dirty": bool(status_short),
            "status_short": status_short.splitlines(),
        },
        "reliability_gate": {
            "artifact": str(gate_path),
            "decision": gate.get("decision"),
            "blocked": bool(gate.get("blocked")),
            "blockers": list(gate.get("blockers") or []),
        },
        "artifacts": artifacts,
        "blocking_config": dict(gate.get("config") or {}),
        "release_policy": dict(release_policy or {}),
        "checks_summary": [
            {
                "name": item.get("name"),
                "passed": bool(item.get("passed")),
                "required": bool(item.get("required")),
                "artifact": item.get("artifact"),
                "actual_value": item.get("actual_value"),
                "required_threshold": item.get("required_threshold"),
            }
            for item in checks
        ],
    }
    report_path = out or (root / DEFAULT_RELEASE_EVIDENCE_PATH)
    if not report_path.is_absolute():
        report_path = root / report_path
    payload["report_path"] = str(report_path)
    if write:
        _write_json(report_path, payload)
    return payload
