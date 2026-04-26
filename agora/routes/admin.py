from __future__ import annotations

from fastapi import APIRouter, Request

from agora.controllers import runtime_controller
from agora.controllers import workflow_controller
from agora.controllers.schemas import (
    IncidentCreateRequest,
    RuntimeStartResponse,
    RuntimeStatusResponse,
    RuntimeStopResponse,
    ToolApproveRequest,
)

router = APIRouter()


@router.post("/v1/tools/approve")
def tools_approve(req: ToolApproveRequest, request: Request) -> dict:
    return workflow_controller.tools_approve(request.app.state.base_dir, req)


@router.get("/v1/audit/{workflow_id}")
def get_audit(workflow_id: str, request: Request) -> dict:
    return workflow_controller.get_audit(request.app.state.base_dir, workflow_id)


@router.get("/v1/consistency/check")
def consistency_check(request: Request) -> dict:
    return workflow_controller.consistency_check(request.app.state.base_dir)


@router.get("/v1/governance/failure-mode")
def governance_failure_mode(request: Request) -> dict:
    return workflow_controller.governance_failure_mode(request.app, request.app.state.base_dir)


@router.get("/v1/governance/traceability")
def governance_traceability(request: Request) -> dict:
    return workflow_controller.governance_traceability(request.app.state.base_dir)


@router.post("/v1/incidents")
def incidents_create(req: IncidentCreateRequest, request: Request) -> dict:
    return workflow_controller.incidents_create(request.app.state.base_dir, req)


@router.post("/v1/redteam/run")
def redteam_run(request: Request) -> dict:
    return workflow_controller.redteam_run(request.app.state.base_dir)


@router.get("/v1/redteam/report")
def redteam_report(request: Request) -> dict:
    return workflow_controller.redteam_report(request.app.state.base_dir)


@router.post("/v1/runtime/start", response_model=RuntimeStartResponse)
def runtime_start(request: Request) -> RuntimeStartResponse:
    return runtime_controller.runtime_start(app=request.app, root=request.app.state.base_dir)


@router.post("/v1/runtime/stop", response_model=RuntimeStopResponse)
def runtime_stop(request: Request) -> RuntimeStopResponse:
    return runtime_controller.runtime_stop(app=request.app)


@router.get("/v1/runtime/status", response_model=RuntimeStatusResponse)
def runtime_status(request: Request) -> RuntimeStatusResponse:
    return runtime_controller.runtime_status(app=request.app, root=request.app.state.base_dir)


@router.get("/v1/runtime/invariants")
def runtime_invariants(request: Request) -> dict:
    return runtime_controller.runtime_invariants(app=request.app, root=request.app.state.base_dir, mode="check")


@router.post("/v1/runtime/invariants/repair")
def runtime_invariants_repair(request: Request) -> dict:
    return runtime_controller.runtime_invariants(app=request.app, root=request.app.state.base_dir, mode="repair-safe")
