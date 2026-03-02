from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from agora.feature_validation import validate_task_features
from agora.models import FALLBACK_FEATURES, TaskFeatures, RoutingDecision
from agora.prompt_binding import is_domain_effective, resolve_prompt_profile
from agora.prompt_registry import compose_binding_hash


def resolve_routing(
    *,
    rule_engine: Any,
    command_text: str,
    raw_features: dict[str, Any] | None,
    subagent_disagreement: bool,
) -> tuple[TaskFeatures, RoutingDecision]:
    features, _gate = validate_task_features(raw_features or FALLBACK_FEATURES.model_dump())
    decision = rule_engine.route(
        features=features,
        command_text=command_text,
        subagent_disagreement=subagent_disagreement,
    )
    return features, decision


def resolve_binding(
    *,
    prompt_registry: Any,
    decision: RoutingDecision,
    task_intent: str,
    requested_domains: list[str] | None,
    operator_allow_bits: set[str],
) -> tuple[str, str, list[Any], str]:
    prompt_profile_id, binding_reason = resolve_prompt_profile(
        workflow_type=decision.workflow_type,
        task_intent=task_intent,
        debate_triggered=decision.debate_triggered,
    )
    if prompt_profile_id.startswith("profile."):
        prompt_assets = prompt_registry.resolve_profile(prompt_profile_id)
    else:
        prompt_assets = [prompt_registry.get_prompt(prompt_profile_id)]

    blocked_prompt_ids: list[str] = []
    entries = prompt_registry.entries
    for asset in prompt_assets:
        entry = entries.get(asset.id)
        if entry is None:
            blocked_prompt_ids.append(asset.id)
            continue
        requires_auth = entry.requires_authorization
        operator_policy_allow = True if requires_auth is None else requires_auth in operator_allow_bits
        catalog_gate = bool(entry.default_enabled) or (requires_auth is not None and operator_policy_allow)
        if not is_domain_effective(
            operator_policy_allow=operator_policy_allow,
            catalog_default_enabled=catalog_gate,
            requested_domains=requested_domains,
            domain_id=asset.id,
            baseline_required=True,
        ):
            blocked_prompt_ids.append(asset.id)
    if blocked_prompt_ids:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "prompt_domain_not_authorized",
                "blocked_prompt_ids": blocked_prompt_ids,
                "profile_id": prompt_profile_id,
            },
        )

    prompt_binding_hash = compose_binding_hash(prompt_assets)
    return prompt_profile_id, binding_reason, prompt_assets, prompt_binding_hash
