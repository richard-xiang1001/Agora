from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class OperatorPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionQuota:
    max_messages_per_minute: int = 0
    window_seconds: int = 60


@dataclass(frozen=True)
class BudgetPolicyDefaults:
    default_on_exceeded: str = "block"
    default_degrade_model: str = "mock"
    default_grace_requests: int = 0


def _to_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _emit_operator_policy_event(
    *,
    audit_dir: Path,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    path = audit_dir / "operator_policy_events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def _parse_env_allow_bits() -> set[str]:
    raw = os.getenv("AGORA_PROMPT_OPERATOR_ALLOW", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _validate_operator_allow(payload: dict[str, Any], policy_path: Path) -> set[str]:
    schema_version = str(payload.get("schema_version", "")).strip()
    if schema_version != "1.0":
        raise OperatorPolicyError(
            f"operator policy schema_version must be '1.0': {policy_path}"
        )
    allow = payload.get("operator_allow", [])
    if not isinstance(allow, list):
        raise OperatorPolicyError(f"operator_allow must be a list: {policy_path}")
    bits: set[str] = set()
    for i, item in enumerate(allow):
        if not isinstance(item, str):
            raise OperatorPolicyError(
                f"operator_allow[{i}] must be string: {policy_path}"
            )
        value = item.strip()
        if not value:
            raise OperatorPolicyError(
                f"operator_allow[{i}] must be non-empty string: {policy_path}"
            )
        bits.add(value)
    return bits


def load_operator_allow_bits(
    *,
    root: Path,
    audit_dir: Path,
    policy_rel_path: str = "config/operator_policy.yaml",
) -> tuple[set[str], str]:
    policy_path = (root / policy_rel_path).resolve()
    ci = _to_bool_env("CI", False)
    env_bits = _parse_env_allow_bits()

    if policy_path.exists():
        try:
            payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
            if not isinstance(payload, dict):
                raise OperatorPolicyError(
                    f"operator policy root payload must be object: {policy_path}"
                )
            bits = _validate_operator_allow(payload, policy_path)
        except Exception as exc:
            _emit_operator_policy_event(
                audit_dir=audit_dir,
                event_type="operator_policy_invalid",
                payload={
                    "policy_path": str(policy_path),
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            )
            if isinstance(exc, OperatorPolicyError):
                raise
            raise OperatorPolicyError(
                f"operator policy parse error: {policy_path}: {exc}"
            ) from exc

        _emit_operator_policy_event(
            audit_dir=audit_dir,
            event_type="operator_policy_file_used",
            payload={
                "policy_path": str(policy_path),
                "operator_allow_bits": sorted(bits),
                "env_ignored": bool(env_bits),
            },
        )
        return bits, "file"

    if ci:
        raise OperatorPolicyError(
            f"operator policy file required in CI: {policy_path}"
        )

    _emit_operator_policy_event(
        audit_dir=audit_dir,
        event_type="operator_policy_env_fallback",
        payload={
            "policy_path": str(policy_path),
            "operator_allow_bits": sorted(env_bits),
            "env_present": bool(env_bits),
        },
    )
    return env_bits, "env_fallback"


def load_session_quota(
    *,
    root: Path,
    policy_rel_path: str = "config/operator_policy.yaml",
) -> SessionQuota:
    policy_path = (root / policy_rel_path).resolve()
    if not policy_path.exists():
        return SessionQuota()
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise OperatorPolicyError(f"operator policy root payload must be object: {policy_path}")
    section = raw.get("session_quota", {})
    if section is None:
        return SessionQuota()
    if not isinstance(section, dict):
        raise OperatorPolicyError(f"session_quota must be object: {policy_path}")
    max_messages = section.get("max_messages_per_minute", 0)
    window_seconds = section.get("window_seconds", 60)
    try:
        max_messages_int = int(max_messages)
        window_seconds_int = int(window_seconds)
    except Exception as exc:  # noqa: BLE001
        raise OperatorPolicyError(f"invalid session_quota numeric fields: {policy_path}") from exc
    if max_messages_int < 0:
        raise OperatorPolicyError(f"session_quota.max_messages_per_minute must be >=0: {policy_path}")
    if window_seconds_int <= 0:
        raise OperatorPolicyError(f"session_quota.window_seconds must be >0: {policy_path}")
    return SessionQuota(
        max_messages_per_minute=max_messages_int,
        window_seconds=window_seconds_int,
    )


def load_budget_policy_defaults(
    *,
    root: Path,
    policy_rel_path: str = "config/operator_policy.yaml",
) -> BudgetPolicyDefaults:
    policy_path = (root / policy_rel_path).resolve()
    if not policy_path.exists():
        return BudgetPolicyDefaults()
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise OperatorPolicyError(f"operator policy root payload must be object: {policy_path}")
    section = raw.get("budget_policy", {})
    if section is None:
        return BudgetPolicyDefaults()
    if not isinstance(section, dict):
        raise OperatorPolicyError(f"budget_policy must be object: {policy_path}")
    mode = str(section.get("default_on_exceeded", "block")).strip()
    if mode not in {"block", "degrade_to_mock", "allow_with_audit"}:
        raise OperatorPolicyError(f"invalid budget_policy.default_on_exceeded: {mode}")
    degrade_model = str(section.get("default_degrade_model", "mock")).strip() or "mock"
    grace = int(section.get("default_grace_requests", 0))
    if grace < 0:
        raise OperatorPolicyError("budget_policy.default_grace_requests must be >=0")
    return BudgetPolicyDefaults(
        default_on_exceeded=mode,
        default_degrade_model=degrade_model,
        default_grace_requests=grace,
    )
