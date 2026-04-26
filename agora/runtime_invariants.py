from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agora.runtime.process_registry import (
    runtime_task_process_snapshot,
    unregister_runtime_task_native_pane,
    unregister_runtime_task_process,
)
from agora.runtime.queue_manager import QueueManager


INVARIANT_SCHEMA_VERSION = "agora_runtime_invariant_report_v1"
INVARIANT_REPORT_PATH = Path("governance/audits/runtime_invariant_report.json")
INVARIANT_REPAIR_LEDGER_PATH = Path("governance/audits/runtime_invariant_repair_ledger.jsonl")
LEGACY_PENDING_ACTION_MIGRATION_ID = "runtime_invariants_legacy_pending_action_v1"
LEGACY_PENDING_ACTION_REASON = "legacy_manual_review_gate_pre_approval_actor"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")


def _finding(
    *,
    finding_id: str,
    severity: str,
    category: str,
    message: str,
    repairable: bool = False,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "category": category,
        "message": message,
        "repairable": bool(repairable),
        "data": dict(data or {}),
    }


def _queue_rows(root: Path) -> dict[str, dict[str, Any]]:
    queue_path = root / "runtime" / "task_queue.jsonl"
    rows: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(queue_path):
        task_id = str(row.get("task_id") or "").strip()
        if task_id:
            rows[task_id] = row
    return rows


def _workflow_pending_actions(root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    pending: dict[tuple[str, str], dict[str, Any]] = {}
    sessions_root = root / "sessions"
    if not sessions_root.exists():
        return pending
    for workflow_path in sessions_root.glob("*/workflows/*/workflow.json"):
        workflow = _read_json(workflow_path, {})
        if not isinstance(workflow, dict):
            continue
        chat_result = workflow.get("chat_result") if isinstance(workflow.get("chat_result"), dict) else {}
        for index, action in enumerate(list(chat_result.get("pending_actions") or [])):
            if not isinstance(action, dict):
                continue
            workflow_id = str(action.get("workflow_id") or workflow.get("workflow_id") or workflow_path.parent.name).strip()
            action_id = str(action.get("action_id") or "").strip()
            if workflow_id and action_id:
                pending[(workflow_id, action_id)] = {"workflow_path": str(workflow_path), "action_index": index, "action": dict(action)}
    return pending


def _workflow_rows(root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    sessions_root = root / "sessions"
    if not sessions_root.exists():
        return rows
    for workflow_path in sessions_root.glob("*/workflows/*/workflow.json"):
        workflow = _read_json(workflow_path, {})
        if not isinstance(workflow, dict):
            continue
        workflow_id = str(workflow.get("workflow_id") or workflow_path.parent.name).strip()
        if workflow_id:
            rows[workflow_id] = {"workflow_path": str(workflow_path), "workflow": workflow}
    return rows


def _latest_actor_rows(root: Path) -> dict[str, dict[str, Any]]:
    actors: dict[str, dict[str, Any]] = {}
    for path in (root / "runtime" / "agent_team_approval_actors").glob("*.jsonl"):
        for row in _read_jsonl(path):
            actor_id = str(row.get("actor_id") or "").strip()
            if actor_id:
                actors[actor_id] = {**row, "_path": str(path)}
    return actors


def _provider_raw_balance(root: Path) -> list[dict[str, Any]]:
    sidechain_dir = root / "runtime" / "agent_sidechains"
    rows: list[dict[str, Any]] = []
    paths = list(sidechain_dir.glob("*.jsonl")) if sidechain_dir.exists() else []
    provider_calls = root / "runtime" / "provider_calls.jsonl"
    if provider_calls.exists():
        paths.append(provider_calls)
    for path in paths:
        calls: dict[str, dict[str, int]] = {}
        for row in _read_jsonl(path):
            kind = str(row.get("kind") or "").strip()
            if kind not in {"provider_raw_request", "provider_raw_response", "provider_raw_error"}:
                continue
            call_id = str(row.get("call_id") or "").strip()
            if not call_id:
                continue
            counter = calls.setdefault(call_id, {"request": 0, "response": 0, "error": 0})
            if kind == "provider_raw_request":
                counter["request"] += 1
            elif kind == "provider_raw_response":
                counter["response"] += 1
            else:
                counter["error"] += 1
        for call_id, counter in calls.items():
            terminal = counter["response"] + counter["error"]
            if counter["request"] != terminal:
                rows.append({"path": str(path), "call_id": call_id, **counter})
    return rows


def _repair_record(*, root: Path, finding: dict[str, Any], action: str, before: Any, after: Any) -> dict[str, Any]:
    record = {
        "schema_version": "agora_runtime_invariant_repair_v1",
        "created_at": _now_iso(),
        "finding_id": str(finding.get("finding_id") or ""),
        "category": str(finding.get("category") or ""),
        "action": str(action or ""),
        "before": before,
        "after": after,
        "non_destructive": True,
    }
    _append_jsonl(root / INVARIANT_REPAIR_LEDGER_PATH, record)
    return record


def _approval_actor_legacy_reason(action: dict[str, Any]) -> str:
    return str(action.get("approval_actor_legacy_reason") or action.get("legacy_reason") or "").strip()


def _is_legacy_manual_review_candidate(action: dict[str, Any]) -> bool:
    execution_meta = action.get("execution_meta") if isinstance(action.get("execution_meta"), dict) else {}
    action_kind = str(action.get("action") or action.get("kind") or "").strip()
    approval_source = str(action.get("approval_source") or execution_meta.get("approval_source") or "").strip()
    approval_class = str(action.get("approval_class") or execution_meta.get("approval_class") or "").strip()
    return (
        action_kind == "manual_review"
        or approval_source == "manual_review_gate"
        or approval_class == "manual_review"
    )


def _action_audit_view(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "action": action.get("action"),
        "status": action.get("status"),
        "reason": action.get("reason"),
        "approval_required": action.get("approval_required"),
        "approval_source": action.get("approval_source"),
        "approval_actor_id": action.get("approval_actor_id"),
        "actor_id": action.get("actor_id"),
        "approval_actor_legacy_reason": action.get("approval_actor_legacy_reason"),
        "legacy_migration_id": action.get("legacy_migration_id"),
        "legacy_marked_at": action.get("legacy_marked_at"),
    }


def _legacy_pending_action_plan(
    *,
    root: Path,
    item: dict[str, Any],
    workflow_id: str,
    action_id: str,
    force: bool = False,
) -> dict[str, Any]:
    workflow_path = Path(str(item.get("workflow_path") or ""))
    if not workflow_path.is_absolute():
        workflow_path = root / workflow_path
    workflow = _read_json(workflow_path, {})
    if not isinstance(workflow, dict):
        raise ValueError(f"Cannot read workflow JSON at {workflow_path}")
    chat_result = workflow.get("chat_result") if isinstance(workflow.get("chat_result"), dict) else {}
    pending_actions = chat_result.get("pending_actions") if isinstance(chat_result.get("pending_actions"), list) else []
    raw_action_index = item.get("action_index")
    action_index = int(raw_action_index) if raw_action_index is not None else -1
    if action_index < 0 or action_index >= len(pending_actions) or not isinstance(pending_actions[action_index], dict):
        raise ValueError(f"Cannot locate pending action {action_id} in {workflow_path}")
    action = pending_actions[action_index]
    if str(action.get("action_id") or "").strip() != action_id:
        raise ValueError(f"Pending action index mismatch for {action_id} in {workflow_path}")
    if not _is_legacy_manual_review_candidate(action):
        raise ValueError(f"Pending action {action_id} is not an eligible legacy manual-review action")
    legacy_reason = _approval_actor_legacy_reason(action)
    return {
        "workflow_id": workflow_id,
        "action_id": action_id,
        "workflow_path": str(workflow_path),
        "action_index": action_index,
        "eligible": True,
        "already_marked": bool(legacy_reason),
        "force": bool(force),
        "would_write": bool(force or not legacy_reason),
        "migration_id": LEGACY_PENDING_ACTION_MIGRATION_ID,
        "legacy_reason": legacy_reason or LEGACY_PENDING_ACTION_REASON,
        "before": _action_audit_view(action),
    }


def _mark_workflow_pending_action_legacy(
    *,
    root: Path,
    item: dict[str, Any],
    workflow_id: str,
    action_id: str,
    finding: dict[str, Any],
    force: bool = False,
) -> dict[str, Any] | None:
    plan = _legacy_pending_action_plan(root=root, item=item, workflow_id=workflow_id, action_id=action_id, force=force)
    if plan.get("already_marked") and not force:
        return None
    workflow_path = Path(str(plan.get("workflow_path") or ""))
    workflow = _read_json(workflow_path, {})
    if not isinstance(workflow, dict):
        raise ValueError(f"Cannot read workflow JSON at {workflow_path}")
    chat_result = workflow.get("chat_result") if isinstance(workflow.get("chat_result"), dict) else {}
    pending_actions = chat_result.get("pending_actions") if isinstance(chat_result.get("pending_actions"), list) else []
    action_index = int(plan.get("action_index") or 0)
    action = pending_actions[action_index]

    before = {
        "workflow_id": workflow_id,
        "workflow_path": str(workflow_path),
        "action_index": action_index,
        "action": _action_audit_view(action),
    }
    if force:
        action["approval_actor_legacy_reason"] = LEGACY_PENDING_ACTION_REASON
        action["legacy_migration_id"] = LEGACY_PENDING_ACTION_MIGRATION_ID
        action["legacy_marked_by"] = "scripts/check_runtime_invariants.py --mode mark-legacy-safe --write --force"
        action["legacy_marked_at"] = _now_iso()
    else:
        action.setdefault("approval_actor_legacy_reason", LEGACY_PENDING_ACTION_REASON)
        action.setdefault("legacy_migration_id", LEGACY_PENDING_ACTION_MIGRATION_ID)
        action.setdefault("legacy_marked_by", "scripts/check_runtime_invariants.py --mode mark-legacy-safe --write")
        action.setdefault("legacy_marked_at", _now_iso())
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = {
        "workflow_id": workflow_id,
        "workflow_path": str(workflow_path),
        "action_index": action_index,
        "action": _action_audit_view(action),
    }
    return _repair_record(
        root=root,
        finding=finding,
        action="mark_workflow_pending_action_legacy",
        before=before,
        after=after,
    )


def check_runtime_invariants(
    *,
    app: Any | None,
    root: Path,
    mode: str = "check",
    write_report: bool = True,
    legacy_write: bool = False,
    legacy_force: bool = False,
) -> dict[str, Any]:
    normalized_mode = str(mode or "check").strip().lower()
    repair = normalized_mode == "repair-safe"
    mark_legacy = normalized_mode == "mark-legacy-safe"
    findings: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []
    legacy_safe_pending_actions: list[dict[str, Any]] = []
    planned_legacy_mutations: list[dict[str, Any]] = []
    queue = _queue_rows(root)
    workflows = _workflow_rows(root)
    terminal_statuses = {"completed", "failed", "cancelled", "aborted"}
    running_statuses = {"queued", "running", "waiting_user"}

    if app is not None:
        process_registry = getattr(app.state, "runtime_task_processes", {})
        if isinstance(process_registry, dict):
            for task_id, process in list(process_registry.items()):
                task = queue.get(str(task_id))
                poll = getattr(process, "poll", lambda: None)()
                orphan = task is None or str(task.get("status") or "").strip() in terminal_statuses
                dead = poll is not None
                if orphan or dead:
                    findings.append(
                        _finding(
                            finding_id=f"process:{task_id}",
                            severity="warning",
                            category="orphan_process",
                            message="Runtime process registry contains a dead or unowned task process.",
                            repairable=True,
                            data={"task_id": str(task_id), "dead": bool(dead), "queue_status": str((task or {}).get("status") or "")},
                        )
                    )
                    if repair:
                        before = {"task_id": str(task_id), "registered": True}
                        unregister_runtime_task_process(app, task_id=str(task_id), process=process)
                        finding = findings[-1]
                        ledger = _repair_record(root=root, finding=finding, action="unregister_runtime_task_process", before=before, after={"registered": False})
                        repairs.append({"finding_id": f"process:{task_id}", "action": "unregister_runtime_task_process", "ledger_path": str(root / INVARIANT_REPAIR_LEDGER_PATH), "ledger": ledger})
        native_registry = getattr(app.state, "runtime_task_native_panes", {})
        if isinstance(native_registry, dict):
            for task_id, pane in list(native_registry.items()):
                task = queue.get(str(task_id))
                orphan = task is None or str(task.get("status") or "").strip() in terminal_statuses
                snapshot = runtime_task_process_snapshot(app, task_id=str(task_id))
                if orphan:
                    findings.append(
                        _finding(
                            finding_id=f"native_pane:{task_id}",
                            severity="warning",
                            category="orphan_native_pane",
                            message="Native pane registry contains a pane that is not owned by a running queue task.",
                            repairable=True,
                            data={"task_id": str(task_id), "snapshot": snapshot, "pane": dict(pane or {})},
                        )
                    )
                    if repair:
                        before = {"task_id": str(task_id), "registered": True, "pane": dict(pane or {})}
                        unregister_runtime_task_native_pane(app, task_id=str(task_id))
                        finding = findings[-1]
                        ledger = _repair_record(root=root, finding=finding, action="unregister_runtime_task_native_pane", before=before, after={"registered": False})
                        repairs.append({"finding_id": f"native_pane:{task_id}", "action": "unregister_runtime_task_native_pane", "ledger_path": str(root / INVARIANT_REPAIR_LEDGER_PATH), "ledger": ledger})

    for task_id, task in queue.items():
        status = str(task.get("status") or "").strip()
        workflow_id = str(task.get("workflow_id") or ((task.get("request") or {}).get("resume_workflow") or {}).get("workflow_id") or "").strip()
        workflow_row = workflows.get(workflow_id) if workflow_id else None
        workflow = workflow_row.get("workflow") if isinstance(workflow_row, dict) else {}
        workflow_status = str((workflow or {}).get("status") or (workflow or {}).get("workflow_status") or "").strip()
        if workflow_id and workflow_row is None and status in running_statuses:
            findings.append(
                _finding(
                    finding_id=f"queue_workflow:{task_id}",
                    severity="critical",
                    category="queue_workflow_missing",
                    message="Running queue task references a workflow that cannot be found.",
                    repairable=False,
                    data={"task_id": task_id, "task_status": status, "workflow_id": workflow_id},
                )
            )
        if workflow_status:
            if status in terminal_statuses and workflow_status not in terminal_statuses:
                findings.append(
                    _finding(
                        finding_id=f"queue_workflow_terminal:{task_id}",
                        severity="critical",
                        category="queue_workflow_status_mismatch",
                        message="Queue task is terminal while workflow remains non-terminal.",
                        repairable=False,
                        data={"task_id": task_id, "task_status": status, "workflow_id": workflow_id, "workflow_status": workflow_status},
                    )
                )
            if status in running_statuses and workflow_status in terminal_statuses:
                findings.append(
                    _finding(
                        finding_id=f"queue_workflow_running:{task_id}",
                        severity="critical",
                        category="queue_workflow_status_mismatch",
                        message="Queue task is active while workflow is terminal.",
                        repairable=False,
                        data={"task_id": task_id, "task_status": status, "workflow_id": workflow_id, "workflow_status": workflow_status},
                    )
                )
        if status == "waiting_user" and workflow_id:
            has_pending = any(key[0] == workflow_id for key in _workflow_pending_actions(root).keys())
            if not has_pending:
                findings.append(
                    _finding(
                        finding_id=f"queue_waiting_user:{task_id}",
                        severity="critical",
                        category="queue_waiting_user_without_pending_action",
                        message="Queue task is waiting_user but the workflow has no pending action.",
                        repairable=False,
                        data={"task_id": task_id, "workflow_id": workflow_id},
                    )
                )

    for task_path in (root / "runtime" / "agent_team_tasks").glob("*.json"):
        payload = _read_json(task_path, {})
        if not isinstance(payload, dict):
            continue
        member_runs = {
            str(row.get("member_id") or "").strip(): row
            for row in list(payload.get("member_runs") or [])
            if isinstance(row, dict) and str(row.get("member_id") or "").strip()
        }
        if not member_runs:
            team_run_id = str(payload.get("team_run_id") or task_path.stem).strip()
            run_path = root / "runtime" / "agent_team_runs.json"
            runs_payload = _read_json(run_path, {})
            for run in list(runs_payload.get("runs") or runs_payload.get("team_runs") or []):
                if isinstance(run, dict) and str(run.get("team_run_id") or "").strip() == team_run_id:
                    member_runs = {
                        str(row.get("member_id") or "").strip(): row
                        for row in list(run.get("member_runs") or [])
                        if isinstance(row, dict) and str(row.get("member_id") or "").strip()
                    }
                    break
        for task in list(payload.get("tasks") or []):
            if not isinstance(task, dict):
                continue
            member_id = str(task.get("member_id") or "").strip()
            run = member_runs.get(member_id)
            if not run:
                continue
            for key in ("access_mode", "permission_mode"):
                task_value = str(task.get(key) or "").strip()
                run_value = str(run.get(key) or "").strip()
                if task_value and run_value and task_value != run_value:
                    findings.append(
                        _finding(
                            finding_id=f"team_config:{task_path.stem}:{member_id}:{key}",
                            severity="critical",
                            category="team_runtime_config_mismatch",
                            message="Team scheduler task and member runtime row disagree on runtime config.",
                            repairable=False,
                            data={"path": str(task_path), "member_id": member_id, "field": key, "task_value": task_value, "member_value": run_value},
                        )
                    )
        subscriptions = payload.get("member_subscriptions") if isinstance(payload.get("member_subscriptions"), dict) else {}
        notification_revision = int(payload.get("notification_revision") or 0)
        for member_id, subscription in subscriptions.items():
            if not isinstance(subscription, dict):
                continue
            last_seen = int(subscription.get("last_seen_revision") or 0)
            if notification_revision and last_seen > notification_revision:
                findings.append(
                    _finding(
                        finding_id=f"subscription:{task_path.stem}:{member_id}",
                        severity="warning",
                        category="subscription_revision_drift",
                        message="Member subscription last_seen_revision is ahead of team notification revision.",
                        repairable=False,
                        data={"path": str(task_path), "member_id": str(member_id), "last_seen_revision": last_seen, "notification_revision": notification_revision},
                    )
                )

    pending_actions = _workflow_pending_actions(root)
    pending_actor_by_workflow_action: dict[tuple[str, str], dict[str, Any]] = {}
    for actor_id, actor in _latest_actor_rows(root).items():
        if str(actor.get("status") or "").strip() != "pending":
            continue
        workflow_id = str(actor.get("workflow_id") or "").strip()
        action_id = str(actor.get("action_id") or "").strip()
        if workflow_id and action_id:
            pending_actor_by_workflow_action[(workflow_id, action_id)] = actor
        if action_id and (workflow_id, action_id) not in pending_actions:
            findings.append(
                _finding(
                    finding_id=f"approval_actor:{actor_id}",
                    severity="critical",
                    category="approval_actor_orphan",
                    message="Pending approval actor has no matching workflow pending action.",
                    repairable=False,
                    data={"actor_id": actor_id, "workflow_id": workflow_id, "action_id": action_id, "path": actor.get("_path")},
                )
            )
    for (workflow_id, action_id), item in pending_actions.items():
        action = dict(item.get("action") or {})
        actor_id = str(action.get("approval_actor_id") or action.get("actor_id") or "").strip()
        legacy_reason = _approval_actor_legacy_reason(action)
        if (workflow_id, action_id) in pending_actor_by_workflow_action:
            continue
        if legacy_reason:
            if mark_legacy and legacy_force and _is_legacy_manual_review_candidate(action):
                try:
                    planned_legacy_mutations.append(
                        _legacy_pending_action_plan(root=root, item=item, workflow_id=workflow_id, action_id=action_id, force=True)
                    )
                    if legacy_write:
                        ledger = _mark_workflow_pending_action_legacy(
                            root=root,
                            item=item,
                            workflow_id=workflow_id,
                            action_id=action_id,
                            finding=_finding(
                                finding_id=f"workflow_pending_action:{workflow_id}:{action_id}",
                                severity="critical",
                                category="workflow_pending_action_missing_approval_actor",
                                message="Workflow pending action has no matching pending approval actor.",
                                repairable=False,
                                data={"workflow_id": workflow_id, "action_id": action_id, "actor_id": actor_id, "workflow_path": item.get("workflow_path")},
                            ),
                            force=True,
                        )
                        if ledger is not None:
                            repairs.append(
                                {
                                    "finding_id": f"workflow_pending_action:{workflow_id}:{action_id}",
                                    "action": "mark_workflow_pending_action_legacy",
                                    "ledger_path": str(root / INVARIANT_REPAIR_LEDGER_PATH),
                                    "ledger": ledger,
                                }
                            )
                except Exception as exc:
                    findings.append(
                        _finding(
                            finding_id=f"workflow_pending_action_legacy_mark:{workflow_id}:{action_id}",
                            severity="critical",
                            category="workflow_pending_action_legacy_mark_failed",
                            message="Failed to force-mark an eligible legacy workflow pending action.",
                            repairable=False,
                            data={"workflow_id": workflow_id, "action_id": action_id, "workflow_path": item.get("workflow_path"), "error": str(exc)},
                        )
                    )
            legacy_safe_pending_actions.append(
                {
                    "workflow_id": workflow_id,
                    "action_id": action_id,
                    "workflow_path": item.get("workflow_path"),
                    "legacy_reason": legacy_reason,
                    "migration_id": action.get("legacy_migration_id"),
                }
            )
            continue
        finding = _finding(
            finding_id=f"workflow_pending_action:{workflow_id}:{action_id}",
            severity="critical",
            category="workflow_pending_action_missing_approval_actor",
            message="Workflow pending action has no matching pending approval actor.",
            repairable=False,
            data={"workflow_id": workflow_id, "action_id": action_id, "actor_id": actor_id, "workflow_path": item.get("workflow_path")},
        )
        if mark_legacy and _is_legacy_manual_review_candidate(action):
            try:
                planned_legacy_mutations.append(
                    _legacy_pending_action_plan(root=root, item=item, workflow_id=workflow_id, action_id=action_id, force=legacy_force)
                )
                ledger = None
                if legacy_write:
                    ledger = _mark_workflow_pending_action_legacy(
                        root=root,
                        item=item,
                        workflow_id=workflow_id,
                        action_id=action_id,
                        finding=finding,
                        force=legacy_force,
                    )
            except Exception as exc:
                findings.append(
                    _finding(
                        finding_id=f"workflow_pending_action_legacy_mark:{workflow_id}:{action_id}",
                        severity="critical",
                        category="workflow_pending_action_legacy_mark_failed",
                        message="Failed to mark an eligible legacy workflow pending action.",
                        repairable=False,
                        data={"workflow_id": workflow_id, "action_id": action_id, "workflow_path": item.get("workflow_path"), "error": str(exc)},
                    )
                )
            else:
                if ledger is not None:
                    repairs.append(
                        {
                            "finding_id": finding["finding_id"],
                            "action": "mark_workflow_pending_action_legacy",
                            "ledger_path": str(root / INVARIANT_REPAIR_LEDGER_PATH),
                            "ledger": ledger,
                        }
                    )
                legacy_safe_pending_actions.append(
                    {
                        "workflow_id": workflow_id,
                        "action_id": action_id,
                        "workflow_path": item.get("workflow_path"),
                        "legacy_reason": LEGACY_PENDING_ACTION_REASON,
                        "migration_id": LEGACY_PENDING_ACTION_MIGRATION_ID,
                    }
                )
            continue
        findings.append(finding)

    for imbalance in _provider_raw_balance(root):
        findings.append(
            _finding(
                finding_id=f"provider_raw:{imbalance['call_id']}",
                severity="warning",
                category="provider_replay_unpaired_raw_call",
                message="Provider raw request/response ledger is unbalanced for a call id.",
                repairable=False,
                data=imbalance,
            )
        )

    summary = {
        "total": len(findings),
        "critical": sum(1 for item in findings if item["severity"] == "critical"),
        "warning": sum(1 for item in findings if item["severity"] == "warning"),
        "repairable": sum(1 for item in findings if item.get("repairable")),
        "repairs_applied": len(repairs),
        "legacy_safe_pending_action_count": len(legacy_safe_pending_actions),
        "planned_legacy_mutation_count": len(planned_legacy_mutations),
    }
    summary["critical_count"] = summary["critical"]
    summary["warning_count"] = summary["warning"]
    summary["finding_count"] = summary["total"]
    payload = {
        "schema_version": INVARIANT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "mode": "repair-safe" if repair else ("mark-legacy-safe" if mark_legacy else "check"),
        "blocked": summary["critical"] > 0,
        "summary": summary,
        "findings": findings,
        "repairs": repairs,
        "legacy_safe_pending_actions": legacy_safe_pending_actions,
        "planned_legacy_mutations": planned_legacy_mutations,
        "legacy_migration": {
            "dry_run": bool(mark_legacy and not legacy_write),
            "write": bool(mark_legacy and legacy_write),
            "force": bool(mark_legacy and legacy_force),
        },
        "repair_ledger_path": str(root / INVARIANT_REPAIR_LEDGER_PATH),
        "report_path": str(root / INVARIANT_REPORT_PATH),
    }
    if write_report:
        _write_json(root / INVARIANT_REPORT_PATH, payload)
    return payload
