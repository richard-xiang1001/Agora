from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from agora.controllers.message_controller import create_message
from agora.controllers.schemas import MessageRequest
from agora.runtime.checkpoint_store import CheckpointStore
from agora.runtime.queue_manager import QueueManager


class RuntimeLoopRunner:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.root = app.state.base_dir
        self.queue = QueueManager(self.root)
        self.checkpoint = CheckpointStore(self.root)

    def recover(self) -> int:
        recovered = self.queue.recover_running_to_queued()
        cp = self.checkpoint.read()
        if cp and cp.get("task_id"):
            task_id = str(cp.get("task_id"))
            task = self.queue.get(task_id)
            if task and task.status == "running":
                self.queue.update(task_id, status="queued")
                recovered += 1
        self.checkpoint.clear()
        return recovered

    def process_pending(self, *, limit: int = 100) -> int:
        processed = 0
        for _ in range(limit):
            task = self.queue.next_queued()
            if task is None:
                break
            self.queue.update(task.task_id, status="running")
            self.app.state.runtime_active_task_id = task.task_id
            self.checkpoint.write({"task_id": task.task_id, "session_id": task.session_id, "status": "running"})
            try:
                req = MessageRequest(**task.request)
                resp = create_message(
                    app=self.app,
                    root=self.root,
                    session_id=task.session_id,
                    req=req,
                    runtime_mode="queued_runtime",
                )
                body = resp.model_dump(mode="json")
                self.queue.update(
                    task.task_id,
                    status="completed",
                    workflow_id=body.get("workflow_id"),
                    response=body,
                    error=None,
                )
            except HTTPException as exc:
                self.queue.update(task.task_id, status="failed", error=str(exc.detail), response=None)
            except Exception as exc:  # noqa: BLE001
                self.queue.update(task.task_id, status="failed", error=f"{exc.__class__.__name__}:{exc}", response=None)
            finally:
                self.checkpoint.clear()
                self.app.state.runtime_active_task_id = None
            processed += 1
        return processed
