from __future__ import annotations

from fastapi import APIRouter, Request

from agora.controllers import ui_controller

router = APIRouter()


@router.get("/v1/ui/doctor")
def ui_doctor(request: Request) -> dict:
    return ui_controller.get_doctor_report(app=request.app, root=request.app.state.base_dir)


@router.get("/v1/ui/reliability-gate")
def ui_reliability_gate(request: Request) -> dict:
    return ui_controller.get_reliability_gate_report(root=request.app.state.base_dir)
