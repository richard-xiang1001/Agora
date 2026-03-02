from __future__ import annotations

from fastapi import APIRouter, Request

from agora.controllers import workflow_controller
from agora.controllers.schemas import ToolDispatchRequest
from agora.models import AuditAppendRequest
from agora.services.audit_service import enforce_internal_auth

router = APIRouter()


@router.post("/internal/audit/append")
def internal_audit_append(req: AuditAppendRequest, request: Request) -> dict:
    enforce_internal_auth(request=request, policy=request.app.state.internal_api_policy)
    return workflow_controller.internal_audit_append(request.app, req)


@router.post("/internal/tools/dispatch")
def internal_tools_dispatch(req: ToolDispatchRequest, request: Request) -> dict:
    enforce_internal_auth(request=request, policy=request.app.state.internal_api_policy)
    return workflow_controller.internal_tools_dispatch(request.app, request.app.state.base_dir, req)


@router.post("/internal/sandbox-gc/run")
def internal_sandbox_gc_run(request: Request) -> dict:
    enforce_internal_auth(request=request, policy=request.app.state.internal_api_policy)
    return workflow_controller.internal_sandbox_gc_run(request.app)
