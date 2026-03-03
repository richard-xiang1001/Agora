from __future__ import annotations

import uuid

from fastapi import APIRouter, Request

from agora.controllers import message_controller, session_controller
from agora.controllers import memory_controller, runtime_controller
from agora.controllers.schemas import (
    InitiativePolicyRequest,
    InitiativePolicyResponse,
    MemoryDecayResponse,
    MemoryIngestRequest,
    MemoryIngestResponse,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryStatsResponse,
    MessageRequest,
    MessageResponse,
    RoutePreviewRequest,
    RuntimeTaskEnqueueResponse,
    RuntimeTaskRequest,
    RuntimeTaskStatusResponse,
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


@router.post("/v1/sessions/{session_id}/initiative/policy", response_model=InitiativePolicyResponse)
def set_session_initiative_policy(
    session_id: str, req: InitiativePolicyRequest, request: Request
) -> InitiativePolicyResponse:
    return session_controller.set_session_initiative_policy(
        root=request.app.state.base_dir,
        session_id=session_id,
        req=req,
        defaults=request.app.state.initiative_policy_defaults,
    )


@router.get("/v1/sessions/{session_id}/initiative/policy", response_model=InitiativePolicyResponse)
def get_session_initiative_policy(session_id: str, request: Request) -> InitiativePolicyResponse:
    return session_controller.get_session_initiative_policy(
        root=request.app.state.base_dir,
        session_id=session_id,
        defaults=request.app.state.initiative_policy_defaults,
    )


@router.post("/v1/sessions/{session_id}/tasks", response_model=RuntimeTaskEnqueueResponse)
def enqueue_session_task(session_id: str, req: RuntimeTaskRequest, request: Request) -> RuntimeTaskEnqueueResponse:
    return runtime_controller.enqueue_task(
        app=request.app,
        root=request.app.state.base_dir,
        session_id=session_id,
        req=req,
    )


@router.get("/v1/sessions/{session_id}/tasks/{task_id}", response_model=RuntimeTaskStatusResponse)
def get_session_task(session_id: str, task_id: str, request: Request) -> RuntimeTaskStatusResponse:
    return runtime_controller.get_task(
        app=request.app,
        root=request.app.state.base_dir,
        session_id=session_id,
        task_id=task_id,
    )


@router.post("/v1/sessions/{session_id}/memory/ingest", response_model=MemoryIngestResponse)
def memory_ingest(session_id: str, req: MemoryIngestRequest, request: Request) -> MemoryIngestResponse:
    return memory_controller.ingest(root=request.app.state.base_dir, session_id=session_id, req=req)


@router.post("/v1/sessions/{session_id}/memory/query", response_model=MemoryQueryResponse)
def memory_query(session_id: str, req: MemoryQueryRequest, request: Request) -> MemoryQueryResponse:
    return memory_controller.query(root=request.app.state.base_dir, session_id=session_id, req=req)


@router.post("/v1/sessions/{session_id}/memory/decay/run", response_model=MemoryDecayResponse)
def memory_decay(session_id: str, request: Request) -> MemoryDecayResponse:
    return memory_controller.decay(root=request.app.state.base_dir, session_id=session_id)


@router.get("/v1/sessions/{session_id}/memory/stats", response_model=MemoryStatsResponse)
def memory_stats(session_id: str, request: Request) -> MemoryStatsResponse:
    return memory_controller.stats(root=request.app.state.base_dir, session_id=session_id)


@router.post("/v1/route/preview")
def route_preview(req: RoutePreviewRequest, request: Request) -> dict:
    return message_controller.route_preview(app=request.app, req=req)
