from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agora.controllers.schemas import SessionBudgetRequest, SessionBudgetResponse, SessionBudgetView
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
