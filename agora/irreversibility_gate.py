from __future__ import annotations

from dataclasses import dataclass

from agora.models import ApprovalState, ToolActionRequest


@dataclass(frozen=True)
class ApprovalDecision:
    requires_approval: bool
    approval_state: ApprovalState | None
    reason: str


class IrreversibilityGate:
    """Only high-risk and irreversible actions require explicit approval in MVP."""

    def require_approval(self, action: ToolActionRequest) -> ApprovalDecision:
        if action.risk_level == "high" and not action.reversible:
            return ApprovalDecision(
                requires_approval=True,
                approval_state=ApprovalState.PENDING,
                reason="high_risk_irreversible",
            )
        return ApprovalDecision(
            requires_approval=False,
            approval_state=None,
            reason="not_required",
        )
