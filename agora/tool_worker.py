from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

import yaml

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
        sandbox_spec_path: str | Path | None = None,
        runtime_capabilities_path: str | Path | None = None,
    ) -> None:
        self.execution_controller = execution_controller
        self.irreversibility_gate = irreversibility_gate
        self.sandbox_spec = self._load_sandbox_spec(sandbox_spec_path)
        self.runtime_capabilities = self._load_runtime_capabilities(runtime_capabilities_path)

    @staticmethod
    def _load_sandbox_spec(path: str | Path | None) -> dict[str, object]:
        if path is None:
            return {}
        p = Path(path)
        if not p.exists():
            return {}
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_runtime_capabilities(path: str | Path | None) -> dict[str, object]:
        default = {
            "l3_isolation_mode": "unimplemented",
            "allow_sandbox_verification_without_l3": False,
            "sandbox_backend": "docker_compose",
        }
        if path is None:
            return default
        p = Path(path)
        if not p.exists():
            return default
        payload = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return default
        merged = dict(default)
        merged.update(payload)
        return merged

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

        try:
            output = self._dispatch(action, Path(base_dir))
        except PermissionError as exc:
            return ToolWorkerResult(
                status="rejected",
                action_id=action.action_id,
                output=None,
                reason=str(exc),
            )
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

        if action.action == "prepare_sandbox_poc":
            wf = action.workflow_id
            raw_tpl = str(
                self.sandbox_spec.get("writable_path", "/tmp/agora-sandbox/{workflow_id}")
            )
            sandbox_dir = Path(raw_tpl.replace("{workflow_id}", wf))
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            poc = sandbox_dir / "poc.txt"
            poc.write_text(str(action.payload.get("content", "poc placeholder")) + "\n", encoding="utf-8")
            return str(poc)

        if action.action == "run_sandbox_verification":
            wf = action.workflow_id
            raw_tpl = str(
                self.sandbox_spec.get("writable_path", "/tmp/agora-sandbox/{workflow_id}")
            )
            sandbox_dir = Path(raw_tpl.replace("{workflow_id}", wf))
            sandbox_dir.mkdir(parents=True, exist_ok=True)
            output = sandbox_dir / "verification_result.json"

            l3_mode = str(self.runtime_capabilities.get("l3_isolation_mode", "unimplemented"))
            backend = str(self.runtime_capabilities.get("sandbox_backend", "docker_compose"))

            if l3_mode == "docker_compose" and backend == "docker_compose":
                if bool(action.payload.get("network_request", False)):
                    raise PermissionError("sandbox_network_denied")
                timeout_seconds = int(self.sandbox_spec.get("timeout_seconds", 10))
                cmd = ["docker", "compose", "version"]
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=timeout_seconds,
                    )
                    output.write_text(
                        json.dumps(
                            {
                                "outcome": "uncertain",
                                "source": "docker_compose",
                                "status": "ok",
                                "detail": proc.stdout.strip(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                except subprocess.TimeoutExpired as exc:
                    output.write_text(json.dumps({"outcome": "infra_error", "source": "docker_compose", "error": "timeout"}) + "\n", encoding="utf-8")
                    raise PermissionError("sandbox_timeout") from exc
                except subprocess.CalledProcessError as exc:
                    output.write_text(json.dumps({"outcome": "infra_error", "source": "docker_compose", "error": "non_zero_exit"}) + "\n", encoding="utf-8")
                    raise PermissionError("sandbox_backend_failed") from exc
                return str(output)

            # Stub branch for non-containerized mode (guarded by ExecutionController in default policy).
            output.write_text('{"outcome":"uncertain","source":"sandbox_stub"}\n', encoding="utf-8")
            return str(output)

        raise PermissionError(f"unsupported action: {action.action}")
