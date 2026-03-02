from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, Request

from agora.audit_daemon import AuditAppendResult, AuditDaemon, sign_request


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def request_fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_internal_api_policy(root: Path, repo_root: Path) -> dict[str, Any]:
    policy_path = root / "config" / "internal_api_policy.yaml"
    if not policy_path.exists():
        policy_path = repo_root / "config" / "internal_api_policy.yaml"
    if not policy_path.exists():
        return {
            "enabled": True,
            "header_name": "X-Agora-Internal-Token",
            "token_env": "AGORA_INTERNAL_API_TOKEN",
            "allow_source_ips": ["127.0.0.1", "::1"],
            "enforce_source_allowlist": True,
        }
    raw = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise HTTPException(status_code=500, detail="invalid_internal_api_policy")
    return {
        "enabled": bool(raw.get("enabled", True)),
        "header_name": str(raw.get("header_name", "X-Agora-Internal-Token")),
        "token_env": str(raw.get("token_env", "AGORA_INTERNAL_API_TOKEN")),
        "allow_source_ips": [str(x) for x in raw.get("allow_source_ips", ["127.0.0.1", "::1"])],
        "enforce_source_allowlist": bool(raw.get("enforce_source_allowlist", True)),
    }


def enforce_internal_auth(policy: dict[str, Any], request: Request) -> None:
    if not bool(policy.get("enabled", True)):
        return
    header_name = str(policy.get("header_name", "X-Agora-Internal-Token"))
    token_env = str(policy.get("token_env", "AGORA_INTERNAL_API_TOKEN"))
    expected = os.getenv(token_env, "").strip()
    presented = request.headers.get(header_name, "").strip()
    if not expected or not presented:
        raise HTTPException(status_code=401, detail="internal_auth_missing")
    if presented != expected:
        raise HTTPException(status_code=403, detail="internal_auth_invalid")
    if bool(policy.get("enforce_source_allowlist", True)):
        allowed = set(str(x) for x in policy.get("allow_source_ips", ["127.0.0.1", "::1"]))
        client_host = request.client.host if request.client else ""
        if client_host == "testclient":
            client_host = "127.0.0.1"
        if client_host not in allowed:
            raise HTTPException(status_code=403, detail="internal_source_denied")


def load_key_store() -> dict[str, dict[str, str]]:
    active = os.getenv("AUDIT_ACTIVE_KEY_ID", "key_v1")
    next_key = os.getenv("AUDIT_NEXT_KEY_ID")
    components = ["gateway", "orchestrator", "tool_worker", "verification"]

    key_store: dict[str, dict[str, str]] = {}
    for component in components:
        env_name = f"AUDIT_KEY_{component.upper()}"
        secret = os.getenv(env_name, f"dev-secret-{component}")
        key_store[component] = {active: secret}
        if next_key:
            key_store[component][next_key] = secret
    return key_store


def build_daemon(base_dir: Path, degradation_policy: dict[str, Any] | None = None) -> AuditDaemon:
    policy = degradation_policy or {}
    audit_policy_path = base_dir / "config" / "audit_policy.yaml"
    if audit_policy_path.exists():
        audit_policy = yaml.safe_load(audit_policy_path.read_text(encoding="utf-8")) or {}
    else:
        audit_policy = {
            "scrub": {
                "enabled": True,
                "max_chars_per_field": {"diff": 500, "error_message": 300, "stderr_tail": 400},
                "scrub_marker": "[scrubbed:{original_len}]",
                "scrubbed_event_field": "scrubbed_fields",
            }
        }
    return AuditDaemon(
        audit_log_path=base_dir / "audit" / "audit.jsonl",
        wal_dir=base_dir / "audit" / "wal",
        key_store=load_key_store(),
        degraded_max_seconds=int(policy.get("max_degraded_seconds", 300)),
        degraded_max_requests=int(policy.get("max_degraded_requests", 50)),
        scrub_policy=audit_policy,
    )


def append_audit_event(
    *,
    daemon: AuditDaemon,
    component_id: str,
    key_id: str,
    secret: str,
    event_type: str,
    payload: dict[str, Any],
    trace_id: str = "trace-local",
) -> AuditAppendResult:
    req = sign_request(
        component_id=component_id,
        key_id=key_id,
        secret=secret,
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        payload=payload,
        trace_id=trace_id,
        timestamp=datetime.now(timezone.utc),
    )
    return daemon.append_event(req)


def find_workflow_dir(root: Path, workflow_id: str) -> Path:
    for p in root.glob(f"sessions/*/workflows/{workflow_id}"):
        if p.is_dir():
            return p
    raise HTTPException(status_code=404, detail="workflow not found")
