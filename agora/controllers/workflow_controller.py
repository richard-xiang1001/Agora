from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from agora.redteam import run_redteam_suite
from agora.sandbox_gc import SandboxGC
from agora.state_projector import StateProjector
from agora.models import ToolActionRequest
from agora.services.audit_service import append_audit_event, find_workflow_dir, now_iso, read_json, write_json


def get_workflow(root: Path, workflow_id: str) -> dict[str, Any]:
    for wf in root.glob(f"sessions/*/workflows/{workflow_id}/workflow.json"):
        return read_json(wf, {})
    raise HTTPException(status_code=404, detail="workflow not found")


def get_workflow_decision(root: Path, workflow_id: str) -> dict[str, Any]:
    for wf in root.glob(f"sessions/*/workflows/{workflow_id}/decision.json"):
        return read_json(wf, {})
    raise HTTPException(status_code=404, detail="decision not found")


def set_workflow_status(root: Path, workflow_id: str, status: str) -> dict[str, Any]:
    for p in root.glob(f"sessions/*/workflows/{workflow_id}/workflow.json"):
        data = read_json(p, {})
        data["status"] = status
        data["updated_at"] = now_iso()
        write_json(p, data)
        return {"workflow_id": workflow_id, "status": status}
    raise HTTPException(status_code=404, detail="workflow not found")


def cancel_workflow(*, app: Any, root: Path, workflow_id: str) -> dict[str, Any]:
    wf_dir = find_workflow_dir(root, workflow_id)
    workflow_path = wf_dir / "workflow.json"
    data = read_json(workflow_path, {})
    status = str(data.get("status", "running"))
    terminal = {"completed", "failed", "cancelled", "reject"}
    if status in terminal:
        return {"workflow_id": workflow_id, "status": "already_terminal"}
    with app.state.workflow_cancel_lock:
        app.state.workflow_cancel_flags.add(workflow_id)
    data["status"] = "cancel_requested"
    data["updated_at"] = now_iso()
    write_json(workflow_path, data)
    return {"workflow_id": workflow_id, "status": "cancel_requested"}


def tools_approve(root: Path, req: Any) -> dict[str, Any]:
    wf_dir = find_workflow_dir(root, req.workflow_id)
    approval_path = wf_dir / "approval.json"
    approval_payload = read_json(approval_path, {"actions": {}})
    actions = dict(approval_payload.get("actions", {}))
    actions[req.action_id] = {
        "status": "approved" if req.approved else "rejected",
        "operator_id": req.operator_id,
        "applied_at": now_iso(),
    }
    approval_payload["actions"] = actions
    write_json(approval_path, approval_payload)
    return {
        "workflow_id": req.workflow_id,
        "action_id": req.action_id,
        "status": "approved" if req.approved else "rejected",
        "operator_id": req.operator_id,
        "applied_at": actions[req.action_id]["applied_at"],
    }


def get_audit(root: Path, workflow_id: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    audit_log = root / "audit" / "audit.jsonl"
    if not audit_log.exists():
        return {"workflow_id": workflow_id, "events": []}
    for line in audit_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("payload", {}).get("workflow_id") == workflow_id:
            events.append(row)
    return {"workflow_id": workflow_id, "events": events}


def consistency_check(root: Path) -> dict[str, Any]:
    audit_path = root / "audit" / "audit.jsonl"
    sqlite_path = root / "indexes" / "state.db"
    projector = StateProjector(audit_path, sqlite_path)
    projector.project_once()
    result = projector.consistency_check()
    return result.__dict__


def governance_failure_mode(app: Any, root: Path) -> dict[str, Any]:
    audit_daemon = app.state.audit_daemon
    snapshot = audit_daemon.get_health_snapshot()
    projector = StateProjector(root / "audit" / "audit.jsonl", root / "indexes" / "state.db")
    c = projector.consistency_check()
    return {
        "audit_mode": snapshot["audit_state"],
        "audit_state": snapshot["audit_state"],
        "degraded_since": snapshot["degraded_since"],
        "normal_since": snapshot["normal_since"],
        "degraded_seconds": snapshot["degraded_seconds"],
        "normal_seconds": snapshot["normal_seconds"],
        "degraded_request_count": snapshot["degraded_request_count"],
        "pending_wal_events": snapshot["pending_wal_events"],
        "wal_size_bytes": snapshot["wal_size_bytes"],
        "recovery_cooldown_seconds": snapshot["recovery_cooldown_seconds"],
        "budget_exceeded": snapshot["budget_exceeded"],
        "last_refresh_cause": snapshot["last_refresh_cause"],
        "degraded_budget": {
            "max_seconds": int(app.state.degradation_policy.get("max_degraded_seconds", 300)),
            "max_requests": int(app.state.degradation_policy.get("max_degraded_requests", 50)),
        },
        "enforcement_mode": (
            "blocked"
            if snapshot["budget_exceeded"] or snapshot["audit_state"] == "readonly"
            else ("restricted" if snapshot["audit_state"] == "degraded" else "none")
        ),
        "index_status": "ok" if c.consistent else "index_stale",
        "timestamp": now_iso(),
    }


def governance_traceability(root: Path) -> dict[str, Any]:
    path = root / "governance" / "traceability.yaml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="traceability not found")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def incidents_create(root: Path, req: Any) -> dict[str, Any]:
    import uuid

    incident_id = req.incident_id or f"AGR-{uuid.uuid4().hex[:6].upper()}"
    payload = {
        "incident_id": incident_id,
        "date": date.today().isoformat(),
        "severity": req.severity,
        "test_category": req.test_category,
        "trigger": req.trigger,
        "root_cause": req.root_cause,
        "affected_components": req.affected_components,
        "status": "open",
        "due_date": req.due_date,
        "auto_escalation_rule": "逾期未关闭，下次发布同 test_category 升级为阻断",
        "resolution_version": None,
    }
    path = root / "incidents" / f"{incident_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return {"incident_id": incident_id, "path": str(path)}


def redteam_run(root: Path) -> dict[str, Any]:
    output = root / "governance" / "redteam" / "report_week6.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = run_redteam_suite(
        suite_path=root / "redteam" / "suite.yaml",
        thresholds_path=root / "redteam" / "thresholds.yaml",
        output_path=output,
    )
    return {
        "generated": str(output),
        "blocked_release": report.blocked_release,
        "categories": [x.__dict__ for x in report.category_results],
    }


def redteam_report(root: Path) -> dict[str, Any]:
    output = root / "governance" / "redteam" / "report_week6.json"
    if not output.exists():
        raise HTTPException(status_code=404, detail="redteam report not found")
    return json.loads(output.read_text(encoding="utf-8"))


def internal_audit_append(app: Any, req: Any) -> dict[str, Any]:
    result = app.state.audit_daemon.append_event(req)
    return {
        "accepted": result.accepted,
        "duplicate": result.duplicate,
        "seq_no": result.seq_no,
        "wrote_to_wal": result.wrote_to_wal,
        "durability_mode": result.durability_mode,
        "audit_state": result.audit_state,
        "health_snapshot": result.health_snapshot,
    }


def internal_tools_dispatch(app: Any, root: Path, req: Any) -> dict[str, Any]:
    wf_dir = find_workflow_dir(root, req.workflow_id)
    session_id = wf_dir.parent.parent.name
    action = ToolActionRequest(
        workflow_id=req.workflow_id,
        action_id=req.action_id,
        action=req.action,
        risk_level=req.risk_level,
        reversible=req.reversible,
        idempotent=req.idempotent,
        payload={**req.payload, "session_id": session_id},
    )
    result = app.state.tool_worker.execute(req.scope, action, root)
    return {
        "workflow_id": req.workflow_id,
        "action_id": req.action_id,
        "status": result.status,
        "reason": result.reason,
        "output": result.output,
    }


def internal_sandbox_gc_run(app: Any) -> dict[str, Any]:
    gc = SandboxGC("/tmp/agora-sandbox", ttl_minutes=30)
    result = gc.run_once()
    append_audit_event(
        daemon=app.state.audit_daemon,
        component_id="verification",
        key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
        secret=os.getenv("AUDIT_KEY_VERIFICATION", "dev-secret-verification"),
        event_type="sandbox_gc_run",
        payload={
            "scanned": result.scanned,
            "cleaned": result.removed,
            "skipped_active": result.skipped_active,
        },
        trace_id="trace-sandbox-gc",
    )
    return {
        "scanned": result.scanned,
        "cleaned": result.removed,
        "skipped_active": result.skipped_active,
    }
