from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agora.audit_daemon import AuditDaemon
from agora.feature_validation import validate_task_features
from agora.models import FALLBACK_FEATURES, AuditAppendRequest
from agora.redteam import run_redteam_suite
from agora.rule_engine import RuleEngine
from agora.sandbox_gc import SandboxGC
from agora.state_projector import StateProjector


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    session_id: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str


class MessageRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    command_text: str = Field(min_length=1)
    raw_features: dict[str, Any] | None = None
    subagent_disagreement: bool = False


class MessageResponse(BaseModel):
    workflow_id: str
    session_id: str
    workflow_type: str
    permissions_scope: str
    debate_triggered: bool
    matched_rule: str


class RoutePreviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    command_text: str = ""
    raw_features: dict[str, Any] | None = None
    subagent_disagreement: bool = False


class ToolApproveRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_id: str
    action_id: str
    approved: bool
    operator_id: str | None = None


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    incident_id: str | None = None
    severity: str
    test_category: str
    trigger: str
    root_cause: str
    affected_components: list[str]
    due_date: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_key_store() -> dict[str, dict[str, str]]:
    active = os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1")
    next_key = os.getenv("AUDIT_NEXT_KEY_ID")
    components = ["gateway", "orchestrator", "tool_worker", "verification"]

    key_store: dict[str, dict[str, str]] = {}
    for component in components:
        env_name = f"AUDIT_KEY_{component.upper()}"
        secret = os.getenv(env_name, f"dev-secret-{component}")
        key_store[component] = {active: secret}
        if next_key:
            key_store[component][next_key] = secret
    return key_store


def _build_daemon(base_dir: Path) -> AuditDaemon:
    return AuditDaemon(
        audit_log_path=base_dir / "audit" / "audit.jsonl",
        wal_dir=base_dir / "audit" / "wal",
        key_store=_load_key_store(),
    )


def create_app(base_dir: str | Path = ".") -> FastAPI:
    root = Path(base_dir)
    app = FastAPI(title="Agora API", version="v7.1")

    rules_path = root / "policy" / "routing_rules.yaml"
    app.state.rule_engine = RuleEngine.from_yaml(rules_path)
    app.state.base_dir = root
    app.state.audit_daemon = _build_daemon(root)

    @app.post("/v1/sessions", response_model=SessionCreateResponse)
    def create_session(req: SessionCreateRequest) -> SessionCreateResponse:
        session_id = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
        session_dir = root / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "claims").mkdir(exist_ok=True)
        (session_dir / "debate").mkdir(exist_ok=True)
        _write_json(
            session_dir / "state.json",
            {
                "session_id": session_id,
                "created_at": _now_iso(),
                "workflows": [],
            },
        )
        return SessionCreateResponse(session_id=session_id)

    @app.post("/v1/sessions/{session_id}/messages", response_model=MessageResponse)
    def submit_message(session_id: str, req: MessageRequest) -> MessageResponse:
        session_dir = root / "sessions" / session_id
        if not session_dir.exists():
            raise HTTPException(status_code=404, detail="session not found")

        features, _gate = validate_task_features(req.raw_features or FALLBACK_FEATURES.model_dump())
        decision = app.state.rule_engine.route(
            features=features,
            command_text=req.command_text,
            subagent_disagreement=req.subagent_disagreement,
        )
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        wf_dir = session_dir / "workflows" / workflow_id
        wf_dir.mkdir(parents=True, exist_ok=True)

        workflow_payload = {
            "workflow_id": workflow_id,
            "session_id": session_id,
            "status": "running",
            "created_at": _now_iso(),
            "command_text": req.command_text,
            "routing": decision.model_dump(mode="json"),
        }
        _write_json(wf_dir / "workflow.json", workflow_payload)

        state_path = session_dir / "state.json"
        state = _read_json(state_path, {"session_id": session_id, "workflows": []})
        workflows = list(state.get("workflows", []))
        workflows.append(workflow_id)
        state["workflows"] = workflows
        _write_json(state_path, state)

        audit_line = {
            "event_id": str(uuid.uuid4()),
            "timestamp": _now_iso(),
            "component": "gateway",
            "event_type": "workflow_created",
            "workflow_id": workflow_id,
            "route": decision.workflow_type,
        }
        with (session_dir / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_line, ensure_ascii=True) + "\n")

        return MessageResponse(
            workflow_id=workflow_id,
            session_id=session_id,
            workflow_type=decision.workflow_type,
            permissions_scope=decision.permissions_scope,
            debate_triggered=decision.debate_triggered,
            matched_rule=decision.matched_rule,
        )

    @app.get("/v1/workflows/{workflow_id}")
    def get_workflow(workflow_id: str) -> dict[str, Any]:
        for wf in root.glob(f"sessions/*/workflows/{workflow_id}/workflow.json"):
            return _read_json(wf, {})
        raise HTTPException(status_code=404, detail="workflow not found")

    @app.get("/v1/workflows/{workflow_id}/decision")
    def get_workflow_decision(workflow_id: str) -> dict[str, Any]:
        for wf in root.glob(f"sessions/*/workflows/{workflow_id}/decision.json"):
            return _read_json(wf, {})
        raise HTTPException(status_code=404, detail="decision not found")

    @app.post("/v1/workflows/{workflow_id}/pause")
    def pause_workflow(workflow_id: str) -> dict[str, Any]:
        return _set_workflow_status(root, workflow_id, "paused")

    @app.post("/v1/workflows/{workflow_id}/resume")
    def resume_workflow(workflow_id: str) -> dict[str, Any]:
        return _set_workflow_status(root, workflow_id, "running")

    @app.post("/v1/tools/approve")
    def tools_approve(req: ToolApproveRequest) -> dict[str, Any]:
        return {
            "workflow_id": req.workflow_id,
            "action_id": req.action_id,
            "approved": req.approved,
            "operator_id": req.operator_id,
            "at": _now_iso(),
        }

    @app.get("/v1/audit/{workflow_id}")
    def get_audit(workflow_id: str) -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for p in root.glob("sessions/*/audit.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("workflow_id") == workflow_id:
                    events.append(row)
        return {"workflow_id": workflow_id, "events": events}

    @app.get("/v1/consistency/check")
    def consistency_check() -> dict[str, Any]:
        audit_path = root / "audit" / "audit.jsonl"
        sqlite_path = root / "indexes" / "state.db"
        projector = StateProjector(audit_path, sqlite_path)
        projector.project_once()
        result = projector.consistency_check()
        return result.__dict__

    @app.post("/v1/route/preview")
    def route_preview(req: RoutePreviewRequest) -> dict[str, Any]:
        features, gate_state = validate_task_features(req.raw_features or FALLBACK_FEATURES.model_dump())
        decision = app.state.rule_engine.route(
            features,
            command_text=req.command_text,
            subagent_disagreement=req.subagent_disagreement,
        )
        return {
            "features": features.model_dump(mode="json"),
            "gate_state": gate_state,
            "matched_rule": decision.matched_rule,
            "final_route": decision.model_dump(mode="json"),
        }

    @app.get("/v1/governance/failure-mode")
    def governance_failure_mode() -> dict[str, Any]:
        audit_daemon: AuditDaemon = app.state.audit_daemon
        projector = StateProjector(root / "audit" / "audit.jsonl", root / "indexes" / "state.db")
        c = projector.consistency_check()
        return {
            "audit_mode": "readonly" if audit_daemon.is_readonly_mode() else "normal",
            "index_status": "ok" if c.consistent else "index_stale",
            "timestamp": _now_iso(),
        }

    @app.get("/v1/governance/traceability")
    def governance_traceability() -> dict[str, Any]:
        path = root / "governance" / "traceability.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail="traceability not found")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    @app.post("/v1/incidents")
    def incidents_create(req: IncidentCreateRequest) -> dict[str, Any]:
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

    @app.post("/v1/redteam/run")
    def redteam_run() -> dict[str, Any]:
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

    @app.get("/v1/redteam/report")
    def redteam_report() -> dict[str, Any]:
        output = root / "governance" / "redteam" / "report_week6.json"
        if not output.exists():
            raise HTTPException(status_code=404, detail="redteam report not found")
        return json.loads(output.read_text(encoding="utf-8"))

    @app.post("/internal/audit/append")
    def internal_audit_append(req: AuditAppendRequest) -> dict[str, Any]:
        result = app.state.audit_daemon.append_event(req)
        return {
            "accepted": result.accepted,
            "duplicate": result.duplicate,
            "seq_no": result.seq_no,
            "wrote_to_wal": result.wrote_to_wal,
        }

    @app.post("/internal/sandbox-gc/run")
    def internal_sandbox_gc_run() -> dict[str, Any]:
        gc = SandboxGC("/tmp/agora-sandbox", ttl_minutes=30)
        result = gc.run_once()
        return {
            "scanned": result.scanned,
            "cleaned": result.cleaned,
            "skipped_active": result.skipped_active,
        }

    return app


def _set_workflow_status(root: Path, workflow_id: str, status: str) -> dict[str, Any]:
    for p in root.glob(f"sessions/*/workflows/{workflow_id}/workflow.json"):
        data = _read_json(p, {})
        data["status"] = status
        data["updated_at"] = _now_iso()
        _write_json(p, data)
        return {"workflow_id": workflow_id, "status": status}
    raise HTTPException(status_code=404, detail="workflow not found")
