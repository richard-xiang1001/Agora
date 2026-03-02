from __future__ import annotations

from fastapi import APIRouter, Request

from agora.controllers import workflow_controller

router = APIRouter()


@router.get("/v1/workflows/{workflow_id}")
def get_workflow(workflow_id: str, request: Request) -> dict:
    return workflow_controller.get_workflow(request.app.state.base_dir, workflow_id)


@router.get("/v1/workflows/{workflow_id}/decision")
def get_workflow_decision(workflow_id: str, request: Request) -> dict:
    return workflow_controller.get_workflow_decision(request.app.state.base_dir, workflow_id)


@router.post("/v1/workflows/{workflow_id}/pause")
def pause_workflow(workflow_id: str, request: Request) -> dict:
    return workflow_controller.set_workflow_status(request.app.state.base_dir, workflow_id, "paused")


@router.post("/v1/workflows/{workflow_id}/resume")
def resume_workflow(workflow_id: str, request: Request) -> dict:
    return workflow_controller.set_workflow_status(request.app.state.base_dir, workflow_id, "running")


@router.post("/v1/workflows/{workflow_id}/cancel")
def cancel_workflow(workflow_id: str, request: Request) -> dict:
    return workflow_controller.cancel_workflow(app=request.app, root=request.app.state.base_dir, workflow_id=workflow_id)
