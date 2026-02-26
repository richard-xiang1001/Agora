from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agora.execution_controller import ExecutionController
from agora.irreversibility_gate import IrreversibilityGate
from agora.models import ApprovalState, ToolActionRequest, ToolAuthorizationResult


@dataclass(frozen=True)
class ToolWorkerResult:
    status: str
    action_id: str
    output: str | None
    reason: str


class ToolWorker:
    """MVP function-dispatch worker with explicit operation enum enforcement."""

    def __init__(
        self,
        execution_controller: ExecutionController,
        irreversibility_gate: IrreversibilityGate,
    ) -> None:
        self.execution_controller = execution_controller
        self.irreversibility_gate = irreversibility_gate

    def execute(self, scope: str, action: ToolActionRequest, base_dir: str | Path) -> ToolWorkerResult:
        gate = self.irreversibility_gate.require_approval(action)
        action = action.model_copy(update={"approval_required": gate.requires_approval})

        auth = self.execution_controller.authorize_action(scope, action)
        if not auth.allowed:
            status = (
                "pending_approval" if auth.approval_state == ApprovalState.PENDING else "rejected"
            )
            return ToolWorkerResult(
                status=status,
                action_id=action.action_id,
                output=None,
                reason=auth.reason,
            )

        output = self._dispatch(action, Path(base_dir))
        return ToolWorkerResult(
            status="allowed",
            action_id=action.action_id,
            output=output,
            reason="executed",
        )

    def _dispatch(self, action: ToolActionRequest, base_dir: Path) -> str:
        if action.action == "read_session_file":
            rel = str(action.payload.get("path", ""))
            path = base_dir / rel
            return path.read_text(encoding="utf-8")

        if action.action == "read_goal_file":
            wf = action.workflow_id
            session = str(action.payload.get("session_id", ""))
            path = base_dir / "sessions" / session / "workflows" / wf / "goal.md"
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8")

        if action.action == "generate_text_report":
            title = str(action.payload.get("title", "report"))
            content = str(action.payload.get("content", ""))
            return f"{title}\n\n{content}".strip()

        if action.action == "write_decision_draft":
            wf = action.workflow_id
            session = str(action.payload.get("session_id", ""))
            out = base_dir / "sessions" / session / "workflows" / wf / "decision_draft.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            text = str(action.payload.get("content", "")).rstrip() + "\n"
            out.write_text(text, encoding="utf-8")
            return str(out)

        raise PermissionError(f"unsupported action: {action.action}")
