from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

SCHEMA_VERSION = "agora_reliability_release_gate_v1"
DEFAULT_CONFIG_PATH = Path("config/reliability_release_gate.yaml")
DEFAULT_REPORT_PATH = Path("governance/audits/reliability_release_gate.json")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_reliability_gate_config(root: Path, config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or (root / DEFAULT_CONFIG_PATH)
    defaults = {
        "thresholds": {
            "desktop_repeat": 3,
            "desktop_required_pass_rate": 1.0,
            "desktop_cleanup_required": True,
            "invariant_max_critical": 0,
            "redteam_max_hard_deny_bypass": 0,
            "require_product_path_release_gate_pass": True,
            "require_migration_dry_run_pass": True,
        },
        "desktop": {
            "default_mode": "electron",
            "live_provider_required": False,
            "native_pane_required": False,
        },
    }
    if not path.exists() or yaml is None:
        return defaults
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return defaults
    if not isinstance(loaded, dict):
        return defaults
    merged = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**dict(merged[key]), **dict(value)}
        else:
            merged[key] = value
    return merged


def _desktop_actuals(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    total = int(summary.get("required_count") or summary.get("case_count") or summary.get("run_count") or 0)
    passed = int(summary.get("required_passed") or summary.get("passed_count") or summary.get("passed_runs") or 0)
    cleanup = report.get("cleanup") if isinstance(report.get("cleanup"), dict) else {}
    runs = report.get("runs") if isinstance(report.get("runs"), list) else []
    cleanup_passed = bool(cleanup.get("passed", True))
    if runs:
        cleanup_passed = all(bool((run.get("cleanup") if isinstance(run.get("cleanup"), dict) else {}).get("passed")) for run in runs if isinstance(run, dict))
    pass_rate = (passed / total) if total else (1.0 if str(report.get("status") or "").strip().lower() in {"passed", "pass"} or bool(report.get("passed")) else 0.0)
    return {"required_count": total, "required_passed": passed, "pass_rate": pass_rate, "cleanup_passed": cleanup_passed}


def _desktop_passed(report: dict[str, Any], *, required_pass_rate: float = 1.0, cleanup_required: bool = True) -> bool:
    if not report:
        return False
    actuals = _desktop_actuals(report)
    if cleanup_required and not bool(actuals["cleanup_passed"]):
        return False
    if float(actuals["pass_rate"]) < float(required_pass_rate):
        return False
    status = str(report.get("status") or "").strip().lower()
    if status in {"passed", "pass"}:
        return True
    if bool(report.get("passed")):
        return True
    if report.get("blocked") is False and str(report.get("mode") or "") == "skip":
        return True
    return int(actuals["required_count"]) > 0 and int(actuals["required_passed"]) >= int(actuals["required_count"])


def evaluate_reliability_release_gate(
    *,
    root: Path,
    config: dict[str, Any] | None = None,
    desktop_report: dict[str, Any] | None = None,
    invariant_report: dict[str, Any] | None = None,
    redteam_report: dict[str, Any] | None = None,
    product_path_report: dict[str, Any] | None = None,
    doctor_report: dict[str, Any] | None = None,
    out: Path | None = None,
) -> dict[str, Any]:
    config = dict(config or load_reliability_gate_config(root))
    thresholds = dict(config.get("thresholds") or {})
    desktop_report = dict(desktop_report or _read_json(root / "governance/audits/desktop_dogfood_gate.json"))
    invariant_report = dict(invariant_report or _read_json(root / "governance/audits/runtime_invariant_report.json"))
    redteam_report = dict(redteam_report or _read_json(root / "governance/audits/capability_redteam_report.json"))
    product_path_report = dict(product_path_report or _read_json(root / "governance/audits/product_path_release_gate.json"))
    doctor_report = dict(doctor_report or _read_json(root / "governance/audits/beta_packaging_readiness.json"))

    invariant_summary = invariant_report.get("summary") if isinstance(invariant_report.get("summary"), dict) else {}
    redteam_summary = redteam_report.get("summary") if isinstance(redteam_report.get("summary"), dict) else {}
    migration = doctor_report.get("schema_migrations") if isinstance(doctor_report.get("schema_migrations"), dict) else {}
    desktop_actuals = _desktop_actuals(desktop_report)
    required_desktop_pass_rate = float(thresholds.get("desktop_required_pass_rate", 1.0) or 1.0)
    desktop_cleanup_required = bool(thresholds.get("desktop_cleanup_required", True))
    checks = [
        {
            "name": "desktop_dogfood_gate",
            "passed": _desktop_passed(
                desktop_report,
                required_pass_rate=required_desktop_pass_rate,
                cleanup_required=desktop_cleanup_required,
            ),
            "required": True,
            "artifact": str(desktop_report.get("report_path") or root / "governance/audits/desktop_dogfood_gate.json"),
            "failure_stage": str(desktop_report.get("failure_stage") or desktop_report.get("failed_stage") or ""),
            "required_threshold": {"pass_rate": required_desktop_pass_rate, "cleanup_required": desktop_cleanup_required},
            "actual_value": desktop_actuals,
        },
        {
            "name": "runtime_invariants",
            "passed": int(invariant_summary.get("critical_count") or 0) <= int(thresholds.get("invariant_max_critical") or 0),
            "required": True,
            "artifact": str(invariant_report.get("report_path") or root / "governance/audits/runtime_invariant_report.json"),
            "failure_stage": "runtime_invariants",
            "required_threshold": {"critical_count_max": int(thresholds.get("invariant_max_critical") or 0)},
            "actual_value": {"critical_count": int(invariant_summary.get("critical_count") or 0)},
        },
        {
            "name": "capability_redteam",
            "passed": (not bool(redteam_report.get("blocked"))) and int(redteam_summary.get("hard_deny_bypass_count") or 0) <= int(thresholds.get("redteam_max_hard_deny_bypass") or 0),
            "required": True,
            "artifact": str(redteam_report.get("report_path") or root / "governance/audits/capability_redteam_report.json"),
            "failure_stage": "capability_redteam",
            "required_threshold": {"hard_deny_bypass_max": int(thresholds.get("redteam_max_hard_deny_bypass") or 0)},
            "actual_value": {
                "hard_deny_bypass_count": int(redteam_summary.get("hard_deny_bypass_count") or 0),
                "critical_failed_count": int(redteam_summary.get("critical_failed_count") or 0),
            },
        },
        {
            "name": "product_path_release_gate",
            "passed": not bool(product_path_report.get("blocked")),
            "required": bool(thresholds.get("require_product_path_release_gate_pass", True)),
            "artifact": str(product_path_report.get("report_path") or root / "governance/audits/product_path_release_gate.json"),
            "failure_stage": "product_path_release_gate",
            "required_threshold": {"blocked": False},
            "actual_value": {"blocked": bool(product_path_report.get("blocked"))},
        },
        {
            "name": "doctor_migration_dry_run",
            "passed": bool(migration.get("passed")) and not bool(doctor_report.get("blocked")),
            "required": bool(thresholds.get("require_migration_dry_run_pass", True)),
            "artifact": str(doctor_report.get("report_path") or root / "governance/audits/beta_packaging_readiness.json"),
            "failure_stage": "doctor_migration_packaging",
            "required_threshold": {"migration_passed": True, "blocked": False},
            "actual_value": {"migration_passed": bool(migration.get("passed")), "blocked": bool(doctor_report.get("blocked"))},
        },
    ]
    blockers = [item for item in checks if bool(item.get("required")) and not bool(item.get("passed"))]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "blocked": bool(blockers),
        "decision": "block" if blockers else "pass",
        "checks": checks,
        "blockers": blockers,
        "config": config,
        "artifacts": {
            "desktop_dogfood": str(checks[0]["artifact"]),
            "runtime_invariants": str(checks[1]["artifact"]),
            "capability_redteam": str(checks[2]["artifact"]),
            "product_path_release_gate": str(checks[3]["artifact"]),
            "beta_packaging_readiness": str(checks[4]["artifact"]),
        },
    }
    report_path = out or (root / DEFAULT_REPORT_PATH)
    payload["report_path"] = str(report_path)
    _write_json(report_path, payload)
    return payload
