from __future__ import annotations

import os
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

import yaml
from fastapi import FastAPI

from agora.debate_executor import DebateExecutor
from agora.execution_controller import ExecutionController
from agora.initiative.policy_engine import load_defaults as load_initiative_defaults
from agora.irreversibility_gate import IrreversibilityGate
from agora.llm_client import build_llm_client, load_llm_policy, validate_openrouter_auth
from agora.operator_policy import (
    load_budget_policy_defaults,
    load_operator_allow_bits,
    load_session_quota,
)
from agora.prompt_registry import load_catalog
from agora.rule_engine import RuleEngine
from agora.routes import admin_router, internal_router, sessions_router, workflows_router
from agora.services.audit_service import append_audit_event, build_daemon, load_internal_api_policy
from agora.subagent_executor import SubagentExecutor
from agora.tool_worker import ToolWorker


def _resolve_config_path(root: Path, repo_root: Path, rel_path: str) -> Path:
    local = root / rel_path
    if local.exists():
        return local
    return repo_root / rel_path


def _load_yaml(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if data is None else data


def create_app(base_dir: str | Path = ".") -> FastAPI:
    root = Path(base_dir)
    repo_root = Path(__file__).resolve().parents[1]

    app = FastAPI(title="Agora API", version="v7.1")
    app.state.base_dir = root

    rules_path = root / "policy" / "routing_rules.yaml"
    scopes_path = _resolve_config_path(root, repo_root, "config/permissions_scopes.yaml")
    runtime_caps_path = _resolve_config_path(root, repo_root, "config/runtime_capabilities.yaml")
    sandbox_spec_path = _resolve_config_path(root, repo_root, "config/sandbox_spec.yaml")
    degradation_policy_path = _resolve_config_path(root, repo_root, "config/audit_degradation_policy.yaml")
    prompt_catalog_path = _resolve_config_path(root, repo_root, "config/prompt_catalog.yaml")
    operator_policy_path = _resolve_config_path(root, repo_root, "config/operator_policy.yaml")
    llm_policy_path = _resolve_config_path(root, repo_root, "config/llm_policy.yaml")

    app.state.degradation_policy = _load_yaml(degradation_policy_path, default={})
    app.state.audit_daemon = build_daemon(root, app.state.degradation_policy)
    app.state.rule_engine = RuleEngine.from_yaml(rules_path)
    app.state.prompt_registry = load_catalog(
        prompt_catalog_path,
        root_dir=repo_root,
        audit_dir=root / "governance" / "audits",
    )

    operator_allow_bits, operator_policy_source = load_operator_allow_bits(
        root=operator_policy_path.parent.parent,
        audit_dir=root / "governance" / "audits",
    )
    app.state.operator_allow_bits = operator_allow_bits
    app.state.operator_policy_source = operator_policy_source
    app.state.session_quota = load_session_quota(root=operator_policy_path.parent.parent)
    app.state.budget_policy_defaults = load_budget_policy_defaults(root=operator_policy_path.parent.parent)
    app.state.initiative_policy_defaults = load_initiative_defaults(root, repo_root)
    app.state.session_rate_windows = {}
    app.state.runtime_running = False
    app.state.runtime_active_task_id = None
    app.state.runtime_processed_count = 0

    app.state.llm_policy = load_llm_policy(llm_policy_path)
    app.state.llm_client = build_llm_client(app.state.llm_policy, root_dir=root, repo_root=repo_root)

    try:
        app.state.llm_auth_meta = validate_openrouter_auth(app.state.llm_policy)
        append_audit_event(
            daemon=app.state.audit_daemon,
            component_id="orchestrator",
            key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
            secret=os.getenv("AUDIT_KEY_ORCHESTRATOR", "dev-secret-orchestrator"),
            event_type="llm_auth_ready",
            payload=app.state.llm_auth_meta,
            trace_id=f"trace-llm-auth-ready-{uuid.uuid4().hex[:8]}",
        )
    except Exception as exc:
        try:
            append_audit_event(
                daemon=app.state.audit_daemon,
                component_id="orchestrator",
                key_id=os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1"),
                secret=os.getenv("AUDIT_KEY_ORCHESTRATOR", "dev-secret-orchestrator"),
                event_type="llm_auth_failed",
                payload={"error_type": exc.__class__.__name__, "error": str(exc)},
                trace_id=f"trace-llm-auth-failed-{uuid.uuid4().hex[:8]}",
            )
        except Exception:
            pass
        raise

    app.state.subagent_executor = SubagentExecutor(prompt_root_dir=str(repo_root))
    app.state.debate_executor = DebateExecutor(prompt_root_dir=repo_root, llm_policy=app.state.llm_policy)
    app.state.execution_controller = ExecutionController(scopes_path, runtime_caps_path)
    app.state.tool_worker = ToolWorker(
        execution_controller=app.state.execution_controller,
        irreversibility_gate=IrreversibilityGate(),
        sandbox_spec_path=sandbox_spec_path,
        runtime_capabilities_path=runtime_caps_path,
    )

    app.state.internal_api_policy = load_internal_api_policy(root, repo_root)
    app.state.workflow_cancel_flags = set()
    app.state.workflow_cancel_lock = Lock()

    app.include_router(sessions_router)
    app.include_router(workflows_router)
    app.include_router(admin_router)
    app.include_router(internal_router)

    return app
