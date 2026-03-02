from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agora.controllers.schemas import MessageRequest, MessageResponse, RoutePreviewRequest
from agora.models import FALLBACK_FEATURES, RoutingDecision
from agora.services import routing_service
from agora.services.audit_service import append_audit_event, now_iso, read_json, request_fingerprint, write_json
from agora.services.execution_service import execute_workflow
from policy.hard_constraints import check_hard_constraints


def _load_budget(session_dir: Path) -> dict[str, Any]:
    return read_json(
        session_dir / "budget.json",
        {
            "max_cost_usd": None,
            "max_tokens": None,
            "consumed_cost_usd": 0.0,
            "consumed_tokens": 0,
        },
    )


def _save_budget(session_dir: Path, budget: dict[str, Any]) -> None:
    write_json(session_dir / "budget.json", budget)


def _consume_budget(session_dir: Path, *, cost_usd: float | None, tokens: int | None) -> dict[str, Any]:
    budget = _load_budget(session_dir)
    budget["consumed_cost_usd"] = round(float(budget.get("consumed_cost_usd", 0.0)) + float(cost_usd or 0.0), 8)
    budget["consumed_tokens"] = int(budget.get("consumed_tokens", 0)) + int(tokens or 0)
    _save_budget(session_dir, budget)
    return budget


def _enforce_budget_or_raise(*, app: Any, session_id: str, session_dir: Path, trace_id: str) -> None:
    budget = _load_budget(session_dir)
    max_cost = budget.get("max_cost_usd")
    max_tokens = budget.get("max_tokens")
    consumed_cost = float(budget.get("consumed_cost_usd", 0.0))
    consumed_tokens = int(budget.get("consumed_tokens", 0))
    exceeded = (max_cost is not None and consumed_cost >= float(max_cost)) or (
        max_tokens is not None and consumed_tokens >= int(max_tokens)
    )
    if not exceeded:
        return
    try:
        append_audit_event(
            daemon=app.state.audit_daemon,
            component_id="gateway",
            key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
            secret=os.getenv("AUDIT_KEY_GATEWAY", "dev-secret-gateway"),
            event_type="session_budget_exceeded",
            payload={
                "session_id": session_id,
                "max_cost_usd": max_cost,
                "max_tokens": max_tokens,
                "consumed_cost_usd": consumed_cost,
                "consumed_tokens": consumed_tokens,
            },
            trace_id=trace_id,
        )
    except Exception:
        pass
    raise HTTPException(status_code=429, detail="budget_exceeded")


def _enforce_rate_limit_or_raise(*, app: Any, session_id: str) -> None:
    quota = getattr(app.state, "session_quota", None)
    if quota is None:
        return
    max_per_min = int(getattr(quota, "max_messages_per_minute", 0))
    window_seconds = int(getattr(quota, "window_seconds", 60))
    if max_per_min <= 0:
        return

    now_ts = time.time()
    windows = app.state.session_rate_windows
    dq = windows.get(session_id)
    if dq is None:
        dq = deque()
        windows[session_id] = dq
    while dq and (now_ts - dq[0]) >= window_seconds:
        dq.popleft()
    if len(dq) >= max_per_min:
        retry_after = max(1, int(window_seconds - (now_ts - dq[0])))
        raise HTTPException(
            status_code=429,
            detail={"error": "session_rate_limited", "retry_after_seconds": retry_after},
        )
    dq.append(now_ts)


def create_message(*, app: Any, root: Path, session_id: str, req: MessageRequest) -> MessageResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")

    _enforce_rate_limit_or_raise(app=app, session_id=session_id)

    idempotency_path = session_dir / "idempotency_index.json"
    idempotency_data = read_json(idempotency_path, {"requests": {}})
    if not isinstance(idempotency_data, dict):
        idempotency_data = {"requests": {}}
    requests_index = idempotency_data.get("requests", {})
    if not isinstance(requests_index, dict):
        requests_index = {}
        idempotency_data["requests"] = requests_index

    trace_id = f"trace-{uuid.uuid4().hex[:12]}"
    fp_payload = {
        "command_text": req.command_text,
        "raw_features": req.raw_features,
        "subagent_disagreement": req.subagent_disagreement,
        "authorization_requested_domains": sorted(req.authorization.requested_domains)
        if req.authorization and req.authorization.requested_domains is not None
        else None,
        "cancel_after_round": req.cancel_after_round,
    }
    req_fingerprint = request_fingerprint(fp_payload)
    if req.request_id:
        entry = requests_index.get(req.request_id)
        if isinstance(entry, dict):
            if str(entry.get("fingerprint", "")) != req_fingerprint:
                raise HTTPException(status_code=409, detail="idempotency_conflict")
            stored = entry.get("response")
            if isinstance(stored, dict):
                stored["idempotency_hit"] = True
                return MessageResponse(**stored)

    _enforce_budget_or_raise(app=app, session_id=session_id, session_dir=session_dir, trace_id=trace_id)

    try:
        hard_match = check_hard_constraints(req.command_text)
    except Exception as exc:
        try:
            append_audit_event(
                daemon=app.state.audit_daemon,
                component_id="gateway",
                key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                secret=os.getenv("AUDIT_KEY_GATEWAY", "dev-secret-gateway"),
                event_type="hard_constraint_guard_error",
                payload={
                    "session_id": session_id,
                    "error_type": exc.__class__.__name__,
                },
                trace_id=f"trace-hard-guard-{session_id}",
            )
        except Exception:
            pass
        raise HTTPException(status_code=503, detail="hard_constraint_guard_error") from exc

    features, _ = routing_service.resolve_routing(
        rule_engine=app.state.rule_engine,
        command_text=req.command_text,
        raw_features=req.raw_features,
        subagent_disagreement=req.subagent_disagreement,
    )

    audit_status = "normal"
    degradation_policy_state = "none"

    if hard_match.hit:
        try:
            audit_result = append_audit_event(
                daemon=app.state.audit_daemon,
                component_id="gateway",
                key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                secret=os.getenv("AUDIT_KEY_GATEWAY", "dev-secret-gateway"),
                event_type="hard_constraint_reject",
                payload={
                    "session_id": session_id,
                    "command_text": req.command_text,
                    "matched_rule": hard_match.rule,
                    "constraint_match_path": getattr(hard_match, "constraint_match_path", "none"),
                },
                trace_id=trace_id,
            )
            if audit_result.health_snapshot:
                audit_status = str(audit_result.health_snapshot.get("audit_state", "normal"))
                if audit_status == "degraded":
                    degradation_policy_state = "restricted_window"
        except Exception:
            audit_status = "degraded"
            degradation_policy_state = "restricted_window"
        decision = RoutingDecision(
            workflow_type="reject",
            permissions_scope="none",
            debate_triggered=False,
            fallback_chain=[],
            matched_rule=f"hard_constraint:{hard_match.rule}",
            feature_confidence=features.confidence,
        )
    else:
        decision = app.state.rule_engine.route(
            features=features,
            command_text=req.command_text,
            subagent_disagreement=req.subagent_disagreement,
        )

    requested_domains = None
    if req.authorization and req.authorization.requested_domains is not None:
        requested_domains = [str(x) for x in req.authorization.requested_domains if str(x).strip()]
    operator_allow_bits = set(app.state.operator_allow_bits)

    prompt_profile_id, binding_reason, prompt_assets, prompt_binding_hash = routing_service.resolve_binding(
        prompt_registry=app.state.prompt_registry,
        decision=decision,
        task_intent=features.task_intent,
        requested_domains=requested_domains,
        operator_allow_bits=operator_allow_bits,
    )

    workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
    wf_dir = session_dir / "workflows" / workflow_id
    wf_dir.mkdir(parents=True, exist_ok=True)

    initial_workflow_payload = {
        "workflow_id": workflow_id,
        "session_id": session_id,
        "status": "running",
        "created_at": now_iso(),
        "command_text": req.command_text,
        "routing": decision.model_dump(mode="json"),
        "prompt_binding": {
            "profile_id": prompt_profile_id,
            "prompt_ids": [x.id for x in prompt_assets],
            "prompt_sha256": {x.id: x.sha256 for x in prompt_assets},
            "binding_hash": prompt_binding_hash,
            "binding_reason": binding_reason,
            "resolved_at": now_iso(),
        },
        "authorization_context": {
            "requested_domains": requested_domains,
            "use_policy_default": requested_domains is None,
            "operator_allow_bits": sorted(operator_allow_bits),
            "operator_policy_source": app.state.operator_policy_source,
        },
        "execution_mode": None,
        "cancel_after_round": req.cancel_after_round,
    }
    write_json(wf_dir / "workflow.json", initial_workflow_payload)

    with app.state.workflow_cancel_lock:
        app.state.workflow_cancel_flags.discard(workflow_id)

    def _is_cancel_requested() -> bool:
        with app.state.workflow_cancel_lock:
            return workflow_id in app.state.workflow_cancel_flags

    try:
        run_result = execute_workflow(
            workflow_type=decision.workflow_type,
            debate_triggered=decision.debate_triggered,
            command_text=req.command_text,
            features_json=features.model_dump(mode="json"),
            features_obj=features,
            prompt_assets=prompt_assets,
            llm_policy=app.state.llm_policy,
            llm_client=app.state.llm_client,
            debate_executor=app.state.debate_executor,
            subagent_executor=app.state.subagent_executor,
            wf_dir=wf_dir,
            cancel_check=_is_cancel_requested,
            cancel_after_round=req.cancel_after_round,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else ""
        event_type = None
        if detail == "debate_execution_auth_failed":
            event_type = "debate_execution_auth_failed"
        elif detail == "debate_execution_failed":
            event_type = "debate_execution_failed"
        elif detail == "subagent_execution_failed":
            event_type = "subagent_execution_failed"
        if event_type:
            try:
                append_audit_event(
                    daemon=app.state.audit_daemon,
                    component_id="orchestrator",
                    key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                    secret=os.getenv("AUDIT_KEY_ORCHESTRATOR", "dev-secret-orchestrator"),
                    event_type=event_type,
                    payload={
                        "session_id": session_id,
                        "workflow_id": workflow_id,
                        "error_type": exc.__class__.__name__,
                        "error": detail,
                    },
                    trace_id=trace_id,
                )
            except Exception:
                pass
        raise

    workflow_payload = dict(initial_workflow_payload)
    workflow_payload["status"] = run_result["workflow_status"]
    workflow_payload["execution_mode"] = run_result["execution_mode"]
    if run_result["verdict_payload"] is not None:
        workflow_payload["verdict"] = run_result["verdict_payload"]
    if run_result["debate_verdict_payload"] is not None:
        workflow_payload["debate_verdict"] = run_result["debate_verdict_payload"]
    if run_result["debate_metrics_payload"] is not None:
        workflow_payload["debate_metrics"] = run_result["debate_metrics_payload"]
    if run_result["cancelled_at_round"] is not None:
        workflow_payload["cancelled_at_round"] = run_result["cancelled_at_round"]
    write_json(wf_dir / "workflow.json", workflow_payload)

    state_path = session_dir / "state.json"
    state = read_json(state_path, {"session_id": session_id, "workflows": []})
    workflows = list(state.get("workflows", []))
    workflows.append(workflow_id)
    state["workflows"] = workflows
    write_json(state_path, state)

    audit_result = None
    snapshot = None
    try:
        audit_result = append_audit_event(
            daemon=app.state.audit_daemon,
            component_id="gateway",
            key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
            secret=os.getenv("AUDIT_KEY_GATEWAY", "dev-secret-gateway"),
            event_type="workflow_created",
            payload={
                "workflow_id": workflow_id,
                "session_id": session_id,
                "route": decision.workflow_type,
            },
            trace_id=trace_id,
        )
    except Exception:
        audit_status = "degraded"
        degradation_policy_state = "restricted_window"
        snapshot = {
            "audit_state": "degraded",
            "degraded_since": now_iso(),
            "degraded_seconds": 0,
            "normal_since": None,
            "normal_seconds": 0,
            "degraded_request_count": 0,
            "pending_wal_events": 0,
            "wal_size_bytes": 0,
            "recovery_cooldown_seconds": 120,
            "budget_exceeded": False,
            "last_updated": now_iso(),
            "last_refresh_cause": "append_error",
        }

    if audit_result and audit_result.health_snapshot:
        snapshot = audit_result.health_snapshot

    if snapshot:
        audit_status = str(snapshot.get("audit_state", "normal"))
        if audit_status == "readonly" and decision.workflow_type != "reject":
            raise HTTPException(status_code=503, detail="audit_readonly_blocked")
        if audit_status == "degraded" and decision.workflow_type != "reject":
            max_seconds = int(app.state.degradation_policy.get("max_degraded_seconds", 300))
            max_requests = int(app.state.degradation_policy.get("max_degraded_requests", 50))
            exceeds = bool(snapshot.get("budget_exceeded")) or (
                int(snapshot.get("degraded_seconds", 0)) >= max_seconds
                or int(snapshot.get("degraded_request_count", 0)) >= max_requests
            )
            if exceeds:
                raise HTTPException(status_code=503, detail="audit_degraded_budget_exceeded")
            allowed_risks = set(
                app.state.degradation_policy.get("allow_during_degraded", {}).get("risk_levels", ["low"])
            )
            allowed_routes = set(
                app.state.degradation_policy.get("allow_during_degraded", {}).get("routes", ["unknown_workflow"])
            )
            allow_requires_tools = bool(
                app.state.degradation_policy.get("allow_during_degraded", {}).get("requires_tools", False)
            )
            if (
                features.risk_level not in allowed_risks
                or decision.workflow_type not in allowed_routes
                or (features.requires_tools and not allow_requires_tools)
            ):
                raise HTTPException(status_code=503, detail="execution_blocked_audit_degraded")
            degradation_policy_state = "restricted_window"

    # session budget consume and per-call cost alert
    cost_used = None
    tokens_used = None
    if isinstance(run_result.get("debate_metrics_payload"), dict):
        m = run_result["debate_metrics_payload"]
        cost_used = m.get("estimated_cost_usd")
        tokens_used = m.get("total_tokens")
    elif isinstance(run_result.get("subagent_llm_meta"), dict):
        m = run_result["subagent_llm_meta"]
        cost_used = m.get("estimated_cost_usd")
        tokens_used = m.get("total_tokens")
    if cost_used is not None or tokens_used is not None:
        budget_after = _consume_budget(session_dir, cost_usd=float(cost_used or 0.0), tokens=int(tokens_used or 0))
        max_cost = budget_after.get("max_cost_usd")
        max_tokens = budget_after.get("max_tokens")
        consumed_cost = float(budget_after.get("consumed_cost_usd", 0.0))
        consumed_tokens = int(budget_after.get("consumed_tokens", 0))
        if (max_cost is not None and consumed_cost > float(max_cost)) or (
            max_tokens is not None and consumed_tokens > int(max_tokens)
        ):
            try:
                append_audit_event(
                    daemon=app.state.audit_daemon,
                    component_id="gateway",
                    key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                    secret=os.getenv("AUDIT_KEY_GATEWAY", "dev-secret-gateway"),
                    event_type="session_budget_exceeded",
                    payload={
                        "session_id": session_id,
                        "max_cost_usd": max_cost,
                        "max_tokens": max_tokens,
                        "consumed_cost_usd": consumed_cost,
                        "consumed_tokens": consumed_tokens,
                    },
                    trace_id=trace_id,
                )
            except Exception:
                pass

    alert_triggered = False
    if isinstance(run_result.get("subagent_llm_meta"), dict):
        alert_triggered = bool(run_result["subagent_llm_meta"].get("cost_alert_exceeded"))
    elif isinstance(run_result.get("debate_metrics_payload"), dict):
        alert_triggered = int(run_result["debate_metrics_payload"].get("cost_alert_exceeded_calls", 0)) > 0
    if alert_triggered:
        try:
            append_audit_event(
                daemon=app.state.audit_daemon,
                component_id="orchestrator",
                key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                secret=os.getenv("AUDIT_KEY_ORCHESTRATOR", "dev-secret-orchestrator"),
                event_type="cost_budget_exceeded",
                payload={"session_id": session_id, "workflow_id": workflow_id},
                trace_id=trace_id,
            )
        except Exception:
            pass

    response = MessageResponse(
        workflow_id=workflow_id,
        session_id=session_id,
        workflow_type=decision.workflow_type,
        permissions_scope=decision.permissions_scope,
        debate_triggered=decision.debate_triggered,
        matched_rule=decision.matched_rule,
        audit_status=audit_status,
        degradation_policy=degradation_policy_state,
        trace_id=trace_id,
        prompt_profile_id=prompt_profile_id,
        prompt_binding_hash=prompt_binding_hash,
        verdict=run_result["verdict_payload"],
        debate_verdict=run_result["debate_verdict_payload"],
        execution_mode=run_result["execution_mode"],
        idempotency_hit=False,
        workflow_status=run_result["workflow_status"],
        cancelled_at_round=run_result.get("cancelled_at_round"),
    )
    if req.request_id:
        requests_index[req.request_id] = {
            "fingerprint": req_fingerprint,
            "workflow_id": workflow_id,
            "created_at": now_iso(),
            "response": response.model_dump(mode="json"),
        }
        idempotency_data["requests"] = requests_index
        write_json(idempotency_path, idempotency_data)

    with app.state.workflow_cancel_lock:
        app.state.workflow_cancel_flags.discard(workflow_id)
    return response


def route_preview(*, app: Any, req: RoutePreviewRequest) -> dict[str, Any]:
    from agora.feature_validation import validate_task_features

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
