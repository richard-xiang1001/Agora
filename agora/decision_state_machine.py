from __future__ import annotations

from agora.models import DecisionStatus, WorkflowContext


def determine_decision_status(context: WorkflowContext) -> DecisionStatus:
    """Apply locked decision priority: SUSPEND_DECISION > NEEDS_REVIEW > FINAL."""

    if context.risk_level == "high":
        if context.verification_outcome.value in {"uncertain", "infra_error"}:
            return DecisionStatus.SUSPEND_DECISION
        if context.hypothesis_rounds > context.max_hypothesis_rounds:
            return DecisionStatus.SUSPEND_DECISION

    if not context.semantic_gate_passed:
        return DecisionStatus.NEEDS_REVIEW
    if not context.structural_gate_passed:
        return DecisionStatus.NEEDS_REVIEW

    return DecisionStatus.FINAL
