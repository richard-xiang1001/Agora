from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agora.models import ApprovalState, ToolActionRequest, ToolAuthorizationResult


class ExecutionController:
    """Enforce machine-checkable permission scopes with deny-by-default behavior."""

    def __init__(self, scopes_path: str | Path) -> None:
        payload = yaml.safe_load(Path(scopes_path).read_text(encoding="utf-8"))
        scopes = payload.get("scopes", {}) if isinstance(payload, dict) else {}
        if not isinstance(scopes, dict):
            raise ValueError("invalid permissions scope config")
        self._scopes: dict[str, dict[str, list[str]]] = scopes

    def enforce(self, scope: str, operation: str) -> None:
        row = self._scopes.get(scope)
        if not row:
            raise PermissionError(f"unknown permissions scope: {scope}")

        allowed = set(row.get("allowed_operations", []))
        denied = set(row.get("denied_operations", []))

        if operation in denied:
            raise PermissionError(f"operation denied by scope policy: {operation}")
        if operation not in allowed:
            raise PermissionError(
                f"operation not allowed by scope policy: scope={scope}, operation={operation}"
            )

    def authorize_action(self, scope: str, action: ToolActionRequest) -> ToolAuthorizationResult:
        try:
            self.enforce(scope, action.action)
        except PermissionError as exc:
            return ToolAuthorizationResult(
                allowed=False,
                reason=str(exc),
                approval_state=ApprovalState.REJECTED,
            )

        if action.approval_required:
            return ToolAuthorizationResult(
                allowed=False,
                reason="requires_approval",
                approval_state=ApprovalState.PENDING,
            )

        return ToolAuthorizationResult(allowed=True, reason="allowed", approval_state=None)


def load_operation_lists(scopes_path: str | Path, scope: str) -> tuple[set[str], set[str]]:
    payload: dict[str, Any] = yaml.safe_load(Path(scopes_path).read_text(encoding="utf-8"))
    scopes = payload.get("scopes", {})
    row = scopes.get(scope, {})
    return set(row.get("allowed_operations", [])), set(row.get("denied_operations", []))
