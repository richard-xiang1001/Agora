from __future__ import annotations

from pathlib import Path
from typing import Any

from agora.services.audit_service import read_json, write_json


DEFAULT_POLICY = {
    "mode": "suggest_only",
    "max_auto_actions_per_hour": 3,
    "require_human_on_budget_exceeded": True,
}


def load_defaults(root: Path, repo_root: Path) -> dict[str, Any]:
    path = root / "config" / "initiative_policy.yaml"
    if not path.exists():
        path = repo_root / "config" / "initiative_policy.yaml"
    if not path.exists():
        return dict(DEFAULT_POLICY)
    data = read_json(path, dict(DEFAULT_POLICY)) if path.suffix == ".json" else None
    if data is not None and isinstance(data, dict):
        return {**DEFAULT_POLICY, **data}
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return dict(DEFAULT_POLICY)
    return {
        "mode": str(raw.get("mode", DEFAULT_POLICY["mode"])),
        "max_auto_actions_per_hour": int(raw.get("max_auto_actions_per_hour", DEFAULT_POLICY["max_auto_actions_per_hour"])),
        "require_human_on_budget_exceeded": bool(raw.get("require_human_on_budget_exceeded", DEFAULT_POLICY["require_human_on_budget_exceeded"])),
    }


def _policy_path(root: Path, session_id: str) -> Path:
    return root / "sessions" / session_id / "initiative_policy.json"


def load_session_policy(root: Path, session_id: str, defaults: dict[str, Any]) -> dict[str, Any]:
    p = _policy_path(root, session_id)
    policy = read_json(p, defaults)
    if not isinstance(policy, dict):
        policy = dict(defaults)
    return {
        "mode": str(policy.get("mode", defaults.get("mode", "suggest_only"))),
        "max_auto_actions_per_hour": int(policy.get("max_auto_actions_per_hour", defaults.get("max_auto_actions_per_hour", 3))),
        "require_human_on_budget_exceeded": bool(policy.get("require_human_on_budget_exceeded", defaults.get("require_human_on_budget_exceeded", True))),
    }


def save_session_policy(root: Path, session_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    p = _policy_path(root, session_id)
    write_json(p, policy)
    return policy
