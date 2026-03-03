from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from agora.controllers import message_controller, session_controller
from agora.controllers.schemas import (
    MessageRequest,
    MessageResponse,
    RoutePreviewRequest,
    SessionBudgetRequest,
    SessionBudgetResponse,
    SessionBudgetPolicyRequest,
    SessionBudgetPolicyResponse,
    SessionCreateRequest,
    SessionCreateResponse,
)

router = APIRouter()


@router.post("/v1/sessions", response_model=SessionCreateResponse)
def create_session(req: SessionCreateRequest, request: Request) -> SessionCreateResponse:
    sid = req.session_id or f"sess_{uuid.uuid4().hex[:12]}"
    data = session_controller.create_session(root=request.app.state.base_dir, session_id=sid)
    return SessionCreateResponse(**data)


@router.post("/v1/sessions/{session_id}/messages", response_model=MessageResponse)
def submit_message(session_id: str, req: MessageRequest, request: Request) -> MessageResponse:
    return message_controller.create_message(
        app=request.app,
        root=request.app.state.base_dir,
        session_id=session_id,
        req=req,
    )


@router.post("/v1/sessions/{session_id}/budget", response_model=SessionBudgetResponse)
def set_session_budget(session_id: str, req: SessionBudgetRequest, request: Request) -> SessionBudgetResponse:
    return session_controller.set_session_budget(
        root=request.app.state.base_dir,
        session_id=session_id,
        req=req,
    )


@router.get("/v1/sessions/{session_id}/budget", response_model=SessionBudgetResponse)
def get_session_budget(session_id: str, request: Request) -> SessionBudgetResponse:
    return session_controller.get_session_budget(
        root=request.app.state.base_dir,
        session_id=session_id,
    )


@router.post("/v1/sessions/{session_id}/budget/policy", response_model=SessionBudgetPolicyResponse)
def set_session_budget_policy(
    session_id: str, req: SessionBudgetPolicyRequest, request: Request
) -> SessionBudgetPolicyResponse:
    return session_controller.set_session_budget_policy(
        root=request.app.state.base_dir,
        session_id=session_id,
        req=req,
        defaults=request.app.state.budget_policy_defaults,
    )


@router.get("/v1/sessions/{session_id}/budget/policy", response_model=SessionBudgetPolicyResponse)
def get_session_budget_policy(session_id: str, request: Request) -> SessionBudgetPolicyResponse:
    return session_controller.get_session_budget_policy(
        root=request.app.state.base_dir,
        session_id=session_id,
        defaults=request.app.state.budget_policy_defaults,
    )


@router.post("/v1/route/preview")
def route_preview(req: RoutePreviewRequest, request: Request) -> dict:
    return message_controller.route_preview(app=request.app, req=req)
