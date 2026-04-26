from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from agora.runtime_invariants import check_runtime_invariants

DOCTOR_SCHEMA_VERSION = "agora_beta_packaging_readiness_v1"
DEFAULT_REPORT_PATH = Path("governance/audits/beta_packaging_readiness.json")
SCHEMA_VERSION_REGISTRY_PATH = Path("runtime/schema_versions.json")

MIGRATION_REGISTRY: tuple[dict[str, str], ...] = (
    {"name": "sessions", "schema_version": "agora_sessions_v1", "path": "sessions"},
    {"name": "runtime_task_queue", "schema_version": "agora_runtime_task_queue_v1", "path": "runtime/task_queue.jsonl"},
    {"name": "agent_team_tasks", "schema_version": "agora_agent_team_tasks_v1", "path": "runtime/agent_team_tasks"},
    {"name": "provider_sidechains", "schema_version": "agora_provider_sidechains_v1", "path": "runtime/agent_sidechains"},
    {"name": "provider_calls", "schema_version": "agora_provider_calls_v1", "path": "runtime/provider_calls.jsonl"},
    {"name": "project_memory_acl_sync_history", "schema_version": "agora_project_memory_acl_sync_history_v1", "path": "memory/project"},
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def run_migration_dry_run(*, root: Path) -> dict[str, Any]:
    current_versions = _read_json(root / SCHEMA_VERSION_REGISTRY_PATH, {})
    if not isinstance(current_versions, dict):
        current_versions = {}
    entries: list[dict[str, Any]] = []
    for item in MIGRATION_REGISTRY:
        rel = Path(item["path"])
        path = root / rel
        current = str(current_versions.get(item["name"]) or "missing").strip()
        target = str(item["schema_version"])
        needs_migration = current != target
        entries.append(
            {
                "name": item["name"],
                "current_schema_version": current,
                "target_schema_version": target,
                "path": str(path),
                "exists": path.exists(),
                "file_count": _count_files(path),
                "needs_migration": needs_migration,
                "planned_writes": [str(root / SCHEMA_VERSION_REGISTRY_PATH)] if needs_migration else [],
                "destructive": False,
                "diff": {"from": current, "to": target} if needs_migration else {},
                "dry_run": "passed",
                "mutated": False,
            }
        )
    return {
        "schema_version": "agora_schema_migration_registry_v1",
        "generated_at": time.time(),
        "mode": "dry-run",
        "passed": True,
        "mutated": False,
        "schema_version_registry_path": str(root / SCHEMA_VERSION_REGISTRY_PATH),
        "entries": entries,
    }


def check_package_readiness(*, root: Path) -> dict[str, Any]:
    package_json = root / "package.json"
    raw = _read_json(package_json, {})
    build = raw.get("build") if isinstance(raw.get("build"), dict) else {}
    files = list(build.get("files") or []) if isinstance(build.get("files"), list) else []
    extra_files = list(build.get("extraFiles") or []) if isinstance(build.get("extraFiles"), list) else []
    forbidden = ("runtime", "sessions", "governance/audits", "governance/audits/*.jsonl", "agora-electron-live-regression")
    entries: list[str] = []
    for item in files:
        entries.append(str(item))
    for item in extra_files:
        if isinstance(item, dict):
            entries.append(str(item.get("from") or ""))
        else:
            entries.append(str(item))
    violations = []
    for entry in entries:
        normalized = entry.strip().rstrip("/")
        for bad in forbidden:
            if normalized == bad or normalized.startswith(f"{bad}/") or bad in normalized:
                violations.append({"entry": entry, "forbidden": bad})
    provable = bool(files or extra_files)
    passed = provable and not violations
    return {
        "passed": passed,
        "provable": provable,
        "package_json": str(package_json),
        "checked_entries": entries,
        "forbidden_patterns": list(forbidden),
        "violations": violations,
    }


def build_doctor_report(*, app: Any | None, root: Path, write_report: bool = True, out: Path | None = None) -> dict[str, Any]:
    invariant = check_runtime_invariants(app=app, root=root, mode="check", write_report=False)
    migration = run_migration_dry_run(root=root)
    package_readiness = check_package_readiness(root=root)
    package_json = root / "package.json"
    config_permissions = root / "config" / "permissions_scopes.yaml"
    mcp_runtime = getattr(getattr(app, "state", None), "mcp_runtime", None) if app is not None else None
    mcp_summary = {}
    if mcp_runtime is not None and hasattr(mcp_runtime, "state_snapshot"):
        try:
            mcp_summary = dict(mcp_runtime.state_snapshot() or {})
        except Exception:
            mcp_summary = {"status": "unavailable"}
    payload = {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "generated_at": time.time(),
        "blocked": bool(invariant.get("blocked") or not migration.get("passed") or not package_readiness.get("passed")),
        "python_runtime": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "electron_sidecar": {
            "package_json": str(package_json),
            "present": package_json.exists(),
        },
        "data_dir": str(root),
        "permissions_config": {
            "path": str(config_permissions),
            "present": config_permissions.exists(),
        },
        "mcp_approval_state": mcp_summary,
        "runtime_invariants": {
            "blocked": bool(invariant.get("blocked")),
            "summary": dict(invariant.get("summary") or {}),
            "report_path": str(invariant.get("report_path") or ""),
        },
        "schema_migrations": migration,
        "package_readiness": package_readiness,
        "dirty_runtime_artifact_policy": {
            "package_excludes_runtime": bool(package_readiness.get("passed")),
            "checked_paths": ["runtime", "sessions", "governance/audits", "runtime/schema_versions.json"],
            "violations": list(package_readiness.get("violations") or []),
        },
        "latest_desktop_dogfood": _read_json(root / "governance/audits/desktop_dogfood_gate.json", {}),
    }
    report_path = out or (root / DEFAULT_REPORT_PATH)
    payload["report_path"] = str(report_path)
    if write_report:
        _write_json(report_path, payload)
    return payload
