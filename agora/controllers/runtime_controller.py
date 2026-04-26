from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agora.controllers.schemas import (
    RuntimeStartResponse,
    RuntimeStatusResponse,
    RuntimeStopResponse,
    RuntimeTaskEnqueueResponse,
    RuntimeTaskRequest,
    RuntimeTaskStatusResponse,
)
from agora.runtime.loop_runner import RuntimeLoopRunner
from agora.runtime_invariants import check_runtime_invariants


def runtime_start(*, app: Any, root: Path) -> RuntimeStartResponse:
    runner = RuntimeLoopRunner(app)
    recovered = runner.recover()
    app.state.runtime_running = True
    processed = runner.process_pending(limit=200)
    app.state.runtime_processed_count = int(getattr(app.state, "runtime_processed_count", 0)) + processed
    return RuntimeStartResponse(running=True, queue_depth=runner.queue.depth(), recovered_tasks=recovered)


def runtime_stop(*, app: Any) -> RuntimeStopResponse:
    app.state.runtime_running = False
    return RuntimeStopResponse(running=False)


def runtime_status(*, app: Any, root: Path) -> RuntimeStatusResponse:
    runner = RuntimeLoopRunner(app)
    invariant_report = check_runtime_invariants(app=app, root=root, mode="check", write_report=False)
    return RuntimeStatusResponse(
        running=bool(getattr(app.state, "runtime_running", False)),
        queue_depth=runner.queue.depth(),
        active_task_id=getattr(app.state, "runtime_active_task_id", None),
        processed_count=int(getattr(app.state, "runtime_processed_count", 0)),
        runtime_invariants={
            "blocked": bool(invariant_report.get("blocked")),
            "summary": dict(invariant_report.get("summary") or {}),
        },
    )


def runtime_invariants(*, app: Any, root: Path, mode: str = "check") -> dict[str, Any]:
    return check_runtime_invariants(app=app, root=root, mode=mode, write_report=True)


def enqueue_task(*, app: Any, root: Path, session_id: str, req: RuntimeTaskRequest) -> RuntimeTaskEnqueueResponse:
    session_dir = root / "sessions" / session_id
    if not session_dir.exists():
        raise HTTPException(status_code=404, detail="session not found")
    runner = RuntimeLoopRunner(app)
    task = runner.queue.enqueue(session_id=session_id, request=req.model_dump(mode="json"))
    if bool(getattr(app.state, "runtime_running", False)):
        processed = runner.process_pending(limit=200)
        app.state.runtime_processed_count = int(getattr(app.state, "runtime_processed_count", 0)) + processed
        task2 = runner.queue.get(task.task_id)
        if task2 is not None:
            task = task2
    return RuntimeTaskEnqueueResponse(task_id=task.task_id, session_id=task.session_id, status=task.status)


def get_task(*, app: Any, root: Path, session_id: str, task_id: str) -> RuntimeTaskStatusResponse:
    runner = RuntimeLoopRunner(app)
    task = runner.queue.get(task_id)
    if task is None or task.session_id != session_id:
        raise HTTPException(status_code=404, detail="task not found")
    return RuntimeTaskStatusResponse(
        task_id=task.task_id,
        session_id=task.session_id,
        status=task.status,
        workflow_id=task.workflow_id,
        error=task.error,
        response=task.response,
    )
