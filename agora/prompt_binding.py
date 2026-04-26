from __future__ import annotations

from typing import Literal


def resolve_prompt_profile(
    *,
    workflow_type: str,
    task_intent: Literal["code_review", "research", "planning", "general", "unknown"],
    debate_triggered: bool,
) -> tuple[str, str]:
    if workflow_type == "reject":
        return "constitution.guard_l1", "hard_constraint_reject"
    if workflow_type == "code_review_workflow":
        if debate_triggered:
            return "profile.debate_code_review", "code_review_debate_flow"
        return "profile.subagent_code_review", "code_review_subagent_flow"
    if workflow_type == "general_workflow":
        if task_intent in {"research", "planning"}:
            return "profile.intent_safe_fallback", "intent_not_yet_specialized"
        return "profile.subagent_general", "general_subagent_flow"
    if workflow_type == "unknown_workflow":
        if task_intent in {"research", "planning"}:
            return "profile.intent_safe_fallback", "intent_not_yet_specialized"
        return "profile.unknown_safe", "unknown_safe_profile"
    if task_intent in {"research", "planning"}:
        return "profile.intent_safe_fallback", "intent_not_yet_specialized"
    return "profile.unknown_safe", "default_safe_profile"


def request_constraint_pass(
    *,
    requested_domains: list[str] | None,
    domain_id: str,
    baseline_required: bool = False,
) -> bool:
    if requested_domains is None:
        return True
    if baseline_required:
        # Request cannot downgrade baseline-required domains.
        return True
    return domain_id in requested_domains


def is_domain_effective(
    *,
    operator_policy_allow: bool,
    catalog_default_enabled: bool,
    requested_domains: list[str] | None,
    domain_id: str,
    baseline_required: bool = False,
) -> bool:
    request_ok = request_constraint_pass(
        requested_domains=requested_domains,
        domain_id=domain_id,
        baseline_required=baseline_required,
    )
    return operator_policy_allow and catalog_default_enabled and request_ok
