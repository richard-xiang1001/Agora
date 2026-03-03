from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agora.controllers.schemas import (
    InitiativePolicyRequest,
    InitiativePolicyResponse,
    InitiativePolicyView,
    SessionBudgetPolicyRequest,
    SessionBudgetPolicyResponse,
    SessionBudgetPolicyView,
    SessionBudgetRequest,
    SessionBudgetResponse,
    SessionBudgetView,
)
from agora.initiative.policy_engine import load_session_policy, save_session_policy
from agora.services.audit_service import now_iso, read_json, write_json


def create_session(*, root: Path, session_id: str) -> dict[str, Any]:
    session_dir = root / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "claims").mkdir(exist_ok=True)
    (session_dir / "debate").mkdir(exist_ok=True)
    write_json(
        session_dir / "state.json",
        {
            "session_id": session_id,
            "created_at": now_iso(),
            "workflows": [],
        },
    )
    return {"session_id": session_id}


def _budget_path(session_dir: Path) -> Path:
    return session_dir / "budget.json"


def _budget_policy_path(session_dir: Path) -> Path:
    return session_dir / "budget_policy.json"


def _load_budget(session_dir: Path) -> dict[str, Any]:
    return read_json(
        _budget_path(session_dir),
        {
            "max_cost_usd": None,
            "max_tokens": None,
            "consumed_cost_usd": 0.0,
            "consumed_tokens": 0,
        },
    )


def _load_budget_policy(
    session_dir: Path,
    *,
    defaults: Any,
) -> dict[str, Any]:
    return read_json(
        _budget_policy_path(session_dir),
        {
            "on_exceeded": str(getattr(defaults, "default_on_exceeded", "block")),
            "degrade_model": str(getattr(defaults, "default_degrade_model", "mock")),
            "grace_requests": int(getattr(defaults, "default_grace_requests", 0)),
            "grace_used": 0,
        },
    )


def _budget_view(session_id: str, budget: dict[str, Any]) -> SessionBudgetResponse:
    max_cost_usd = budget.get("max_cost_usd")
    max_tokens = budget.get("max_tokens")
    consumed_cost_usd = float(budget.get("consumed_cost_usd", 0.0))
    consumed_tokens = int(budget.get("consumed_tokens", 0))
    remaining_cost_usd = None if max_cost_usd is None else float(max_cost_usd) - consumed_cost_usd
    remaining_tokens = None if max_tokens is None else int(max_tokens) - consumed_tokens
    return SessionBudgetResponse(
        session_id=session_id,
        budget=SessionBudgetView(
            max_cost_usd=max_cost_usd,
            max_tokens=max_tokens,
            consumed_cost_usd=consumed_cost_usd,
            consumed_tokens=consumed_tokens,
            remaining_cost_usd=remaining_cost_usd,
            remaining_tokens=remaining_tokens,
        ),
    )


def set_session_budget(*, root: Path, session_id: str, req: SessionBudgetRequest) -> SessionBudgetResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    budget = _load_budget(session_dir)
    budget["max_cost_usd"] = req.max_cost_usd
    budget["max_tokens"] = req.max_tokens
    write_json(_budget_path(session_dir), budget)
    return _budget_view(session_id, budget)


def get_session_budget(*, root: Path, session_id: str) -> SessionBudgetResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    budget = _load_budget(session_dir)
    return _budget_view(session_id, budget)


def set_session_budget_policy(
    *,
    root: Path,
    session_id: str,
    req: SessionBudgetPolicyRequest,
    defaults: Any,
) -> SessionBudgetPolicyResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    current = _load_budget_policy(session_dir, defaults=defaults)
    payload = {
        "on_exceeded": req.on_exceeded,
        "degrade_model": req.degrade_model,
        "grace_requests": req.grace_requests,
        "grace_used": int(current.get("grace_used", 0)),
    }
    write_json(_budget_policy_path(session_dir), payload)
    return SessionBudgetPolicyResponse(
        session_id=session_id,
        budget_policy=SessionBudgetPolicyView(**payload),
    )


def get_session_budget_policy(*, root: Path, session_id: str, defaults: Any) -> SessionBudgetPolicyResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    payload = _load_budget_policy(session_dir, defaults=defaults)
    write_json(_budget_policy_path(session_dir), payload)
    return SessionBudgetPolicyResponse(
        session_id=session_id,
        budget_policy=SessionBudgetPolicyView(**payload),
    )


def set_session_initiative_policy(
    *,
    root: Path,
    session_id: str,
    req: InitiativePolicyRequest,
    defaults: dict[str, Any],
) -> InitiativePolicyResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    payload = {
        "mode": req.mode,
        "max_auto_actions_per_hour": req.max_auto_actions_per_hour,
        "require_human_on_budget_exceeded": req.require_human_on_budget_exceeded,
    }
    save_session_policy(root, session_id, payload)
    return InitiativePolicyResponse(
        session_id=session_id,
        initiative_policy=InitiativePolicyView(**payload),
    )


def get_session_initiative_policy(
    *,
    root: Path,
    session_id: str,
    defaults: dict[str, Any],
) -> InitiativePolicyResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    payload = load_session_policy(root, session_id, defaults)
    save_session_policy(root, session_id, payload)
    return InitiativePolicyResponse(
        session_id=session_id,
        initiative_policy=InitiativePolicyView(**payload),
    )
