from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from agora.claude_project_import import ClaudeProjectImportBridge
from agora.services.audit_service import now_iso, read_json, write_json


SUPPORTED_HOOK_EVENTS = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Stop",
    "SubagentStop",
    "Notification",
)

_GLOBAL_HOOKS_REL_PATH = Path("config/hooks.json")
_HOOK_TRUST_REL_PATH = Path("runtime/hook_policy.json")


@dataclass(frozen=True)
class HookExecutionResult:
    continue_execution: bool = True
    decision: str = "allow"
    reason: str = ""
    updated_input: dict[str, Any] | None = None
    updated_output: str | None = None
    updated_prompt: str = ""
    additional_contexts: tuple[str, ...] = ()
    events: tuple[dict[str, Any], ...] = ()


class UserHookRuntime:
    def __init__(self, *, root_dir: Path, claude_import_bridge: ClaudeProjectImportBridge | None = None) -> None:
        self._root_dir = root_dir.resolve()
        self._global_config_path = (self._root_dir / _GLOBAL_HOOKS_REL_PATH).resolve()
        self._trust_path = (self._root_dir / _HOOK_TRUST_REL_PATH).resolve()
        self._claude_import_bridge = claude_import_bridge

    @property
    def global_config_path(self) -> Path:
        return self._global_config_path

    @property
    def trust_path(self) -> Path:
        return self._trust_path

    def list_hooks(self, *, workspace_root: Path | str | None = None) -> dict[str, Any]:
        resolved_workspace_root = self._resolve_workspace_root(workspace_root)
        items: list[dict[str, Any]] = []
        for source in self._load_sources(workspace_root=resolved_workspace_root):
            hooks = source["hooks"]
            trusted = bool(source["trusted"])
            path = str(source["path"])
            for event_name in SUPPORTED_HOOK_EVENTS:
                for index, spec in enumerate(list(hooks.get(event_name) or []), start=1):
                    items.append(
                        {
                            "hook_id": str(spec.get("hook_id") or f"{source['source']}:{event_name}:{index}"),
                            "event": event_name,
                            "source": source["source"],
                            "path": path,
                            "trusted": trusted,
                            "enabled": bool(spec.get("enabled", True)),
                            "matcher": str(spec.get("matcher") or "*"),
                            "command": str(spec.get("command") or "").strip(),
                            "timeout_seconds": int(spec.get("timeout_seconds") or 10),
                        }
                    )
        return {
            "global_config_path": str(self._global_config_path),
            "project_config_path": str(self._project_config_path(resolved_workspace_root)),
            "trust_policy_path": str(self._trust_path),
            "trusted_project_roots": self.trusted_project_roots(),
            "workspace_root": str(resolved_workspace_root),
            "supported_events": list(SUPPORTED_HOOK_EVENTS),
            "hooks": items,
        }

    def trusted_project_roots(self) -> list[str]:
        policy = self._load_trust_policy()
        values: list[str] = []
        for item in list(policy.get("trusted_project_roots") or []):
            value = str(item or "").strip()
            if not value:
                continue
            try:
                resolved = str(Path(value).expanduser().resolve())
            except Exception:
                continue
            if resolved not in values:
                values.append(resolved)
        return values

    def set_project_trust(self, *, project_root: Path | str, trusted: bool) -> dict[str, Any]:
        resolved = self._resolve_workspace_root(project_root)
        roots = self.trusted_project_roots()
        root_text = str(resolved)
        if trusted:
            if root_text not in roots:
                roots.append(root_text)
        else:
            roots = [item for item in roots if item != root_text]
        payload = {"trusted_project_roots": roots, "updated_at": now_iso()}
        write_json(self._trust_path, payload)
        return payload

    def is_project_trusted(self, project_root: Path | str) -> bool:
        return self._is_project_trusted(self._resolve_workspace_root(project_root))

    def run_user_prompt_submit(
        self,
        *,
        workspace_root: Path | str | None,
        session_id: str,
        workflow_id: str,
        command_text: str,
        agent_run: dict[str, Any] | None = None,
    ) -> HookExecutionResult:
        return self._run_event(
            event_name="UserPromptSubmit",
            workspace_root=workspace_root,
            match_value="",
            payload={
                "session_id": session_id,
                "workflow_id": workflow_id,
                "command_text": str(command_text or ""),
                "agent_run": dict(agent_run or {}),
            },
        )

    def run_pre_tool_use(
        self,
        *,
        workspace_root: Path | str | None,
        session_id: str,
        workflow_id: str,
        action_name: str,
        action_payload: dict[str, Any],
    ) -> HookExecutionResult:
        return self._run_event(
            event_name="PreToolUse",
            workspace_root=workspace_root,
            match_value=action_name,
            payload={
                "session_id": session_id,
                "workflow_id": workflow_id,
                "action": str(action_name or ""),
                "payload": dict(action_payload or {}),
            },
        )

    def run_post_tool_use(
        self,
        *,
        workspace_root: Path | str | None,
        session_id: str,
        workflow_id: str,
        action_name: str,
        action_payload: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> HookExecutionResult:
        return self._run_event(
            event_name="PostToolUse",
            workspace_root=workspace_root,
            match_value=action_name,
            payload={
                "session_id": session_id,
                "workflow_id": workflow_id,
                "action": str(action_name or ""),
                "payload": dict(action_payload or {}),
                "tool_result": dict(tool_result or {}),
            },
        )

    def run_stop(
        self,
        *,
        workspace_root: Path | str | None,
        session_id: str,
        workflow_id: str,
        workflow_status: str,
        execution_mode: str,
        assistant_text: str,
    ) -> HookExecutionResult:
        return self._run_event(
            event_name="Stop",
            workspace_root=workspace_root,
            match_value="",
            payload={
                "session_id": session_id,
                "workflow_id": workflow_id,
                "workflow_status": str(workflow_status or ""),
                "execution_mode": str(execution_mode or ""),
                "assistant_text": str(assistant_text or ""),
            },
        )

    def _run_event(
        self,
        *,
        event_name: str,
        workspace_root: Path | str | None,
        match_value: str,
        payload: dict[str, Any],
    ) -> HookExecutionResult:
        resolved_workspace_root = self._resolve_workspace_root(workspace_root)
        if event_name not in SUPPORTED_HOOK_EVENTS:
            return HookExecutionResult()
        events: list[dict[str, Any]] = []
        additional_contexts: list[str] = []
        current_input = dict(payload.get("payload") or {}) if isinstance(payload.get("payload"), dict) else None
        current_output = None
        current_prompt = str(payload.get("command_text") or "")
        project_path = self._project_config_path(resolved_workspace_root)
        if project_path.exists() and not self._is_project_trusted(resolved_workspace_root):
            events.append(
                self._event(
                    "user_hook_skipped_untrusted",
                    {
                        "hook_event": event_name,
                        "workspace_root": str(resolved_workspace_root),
                        "config_path": str(project_path),
                    },
                )
            )
        if self._claude_import_bridge is not None and not self._is_project_trusted(resolved_workspace_root):
            try:
                self._claude_import_bridge.refresh()
                imported_hook_sources = list(self._claude_import_bridge.imported_hook_sources())
            except Exception:
                imported_hook_sources = []
            for imported in imported_hook_sources:
                if str(imported.source or "").strip() not in {"claude_project", "claude_local"}:
                    continue
                events.append(
                    self._event(
                        "user_hook_skipped_untrusted",
                        {
                            "hook_event": event_name,
                            "workspace_root": str(resolved_workspace_root),
                            "config_path": imported.path,
                            "source": imported.source,
                        },
                    )
                )
        for source in self._load_sources(workspace_root=resolved_workspace_root):
            for spec in list((source["hooks"] or {}).get(event_name) or []):
                if not bool(spec.get("enabled", True)):
                    continue
                if not self._matches(str(spec.get("matcher") or "*"), str(match_value or "")):
                    continue
                command = str(spec.get("command") or "").strip()
                if not command:
                    continue
                hook_id = str(spec.get("hook_id") or f"{source['source']}:{event_name}:{len(events) + 1}")
                input_payload = dict(payload)
                if current_input is not None:
                    input_payload["payload"] = dict(current_input)
                if current_output is not None:
                    input_payload["tool_result"] = {
                        **dict(input_payload.get("tool_result") or {}),
                        "output": current_output,
                    }
                if current_prompt:
                    input_payload["command_text"] = current_prompt
                result, hook_events = self._execute_command_hook(
                    hook_id=hook_id,
                    command=command,
                    timeout_seconds=int(spec.get("timeout_seconds") or 10),
                    event_name=event_name,
                    workspace_root=resolved_workspace_root,
                    payload=input_payload,
                    source=str(source["source"]),
                )
                events.extend(hook_events)
                additional_contexts.extend(list(result.additional_contexts or ()))
                if result.updated_input is not None:
                    current_input = dict(result.updated_input)
                if str(result.updated_output or "").strip():
                    current_output = str(result.updated_output or "")
                if str(result.updated_prompt or "").strip():
                    current_prompt = str(result.updated_prompt or "").strip()
                if not result.continue_execution or str(result.decision or "allow") == "deny":
                    return HookExecutionResult(
                        continue_execution=False,
                        decision="deny",
                        reason=str(result.reason or "hook_denied"),
                        updated_input=current_input,
                        updated_output=current_output,
                        updated_prompt=current_prompt,
                        additional_contexts=tuple(additional_contexts),
                        events=tuple(events),
                    )
        return HookExecutionResult(
            continue_execution=True,
            decision="allow",
            updated_input=current_input,
            updated_output=current_output,
            updated_prompt=current_prompt,
            additional_contexts=tuple(additional_contexts),
            events=tuple(events),
        )

    def _execute_command_hook(
        self,
        *,
        hook_id: str,
        command: str,
        timeout_seconds: int,
        event_name: str,
        workspace_root: Path,
        payload: dict[str, Any],
        source: str,
    ) -> tuple[HookExecutionResult, list[dict[str, Any]]]:
        timeout = max(1, int(timeout_seconds or 10))
        env = dict(os.environ)
        if self._claude_import_bridge is not None:
            try:
                self._claude_import_bridge.refresh()
                env.update(self._claude_import_bridge.effective_env())
            except Exception:
                pass
        env["AGORA_PROJECT_DIR"] = str(workspace_root)
        env["AGORA_HOOK_EVENT"] = event_name
        env["AGORA_HOOK_SOURCE"] = source
        env["AGORA_HOOK_ID"] = hook_id
        events: list[dict[str, Any]] = []
        try:
            proc = subprocess.run(
                ["/bin/zsh", "-lc", command],
                cwd=str(workspace_root),
                input=json.dumps(payload, ensure_ascii=True),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            reason = f"hook_timeout:{hook_id}"
            events.append(
                self._event(
                    "user_hook_failed",
                    {
                        "hook_event": event_name,
                        "hook_id": hook_id,
                        "source": source,
                        "failure": "timeout",
                        "timeout_seconds": timeout,
                    },
                )
            )
            return HookExecutionResult(continue_execution=event_name not in {"UserPromptSubmit", "PreToolUse"}, decision="deny", reason=reason), events
        if proc.returncode != 0:
            reason = f"hook_command_failed:{hook_id}"
            events.append(
                self._event(
                    "user_hook_failed",
                    {
                        "hook_event": event_name,
                        "hook_id": hook_id,
                        "source": source,
                        "failure": "non_zero_exit",
                        "returncode": int(proc.returncode),
                        "stderr": str(proc.stderr or "").strip(),
                    },
                )
            )
            return HookExecutionResult(continue_execution=event_name not in {"UserPromptSubmit", "PreToolUse"}, decision="deny", reason=reason), events
        parsed = self._parse_hook_stdout(proc.stdout)
        decision = str(parsed.get("decision") or "allow").strip().lower() or "allow"
        continue_execution = bool(parsed.get("continue", True))
        if decision not in {"allow", "deny"}:
            decision = "allow"
        updated_input = parsed.get("updated_input") if isinstance(parsed.get("updated_input"), dict) else None
        updated_output = ""
        raw_updated_output = parsed.get("updated_output")
        if isinstance(raw_updated_output, str):
            updated_output = raw_updated_output
        elif isinstance(raw_updated_output, dict) and isinstance(raw_updated_output.get("output"), str):
            updated_output = str(raw_updated_output.get("output") or "")
        updated_prompt = str(parsed.get("updated_prompt") or "").strip()
        additional_contexts = self._normalize_additional_contexts(parsed.get("additional_context"))
        events.append(
            self._event(
                "user_hook_applied",
                {
                    "hook_event": event_name,
                    "hook_id": hook_id,
                    "source": source,
                    "decision": decision,
                    "continue": continue_execution,
                    "mutated_input": updated_input is not None,
                    "mutated_output": bool(updated_output),
                    "mutated_prompt": bool(updated_prompt),
                    "additional_context_count": len(additional_contexts),
                },
            )
        )
        return (
            HookExecutionResult(
                continue_execution=continue_execution,
                decision=decision,
                reason=str(parsed.get("reason") or "").strip(),
                updated_input=updated_input,
                updated_output=updated_output or None,
                updated_prompt=updated_prompt,
                additional_contexts=tuple(additional_contexts),
            ),
            events,
        )

    @staticmethod
    def _parse_hook_stdout(stdout: str) -> dict[str, Any]:
        text = str(stdout or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {"additional_context": text}

    @staticmethod
    def _normalize_additional_contexts(value: Any) -> list[str]:
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, list):
            items: list[str] = []
            for item in value:
                text = str(item or "").strip()
                if text:
                    items.append(text)
            return items
        return []

    @staticmethod
    def _matches(pattern: str, value: str) -> bool:
        normalized_pattern = str(pattern or "*").strip()
        normalized_value = str(value or "").strip()
        if not normalized_pattern or normalized_pattern == "*":
            return True
        if normalized_pattern.startswith("^"):
            try:
                return re.search(normalized_pattern, normalized_value) is not None
            except re.error:
                return False
        if "|" in normalized_pattern:
            return normalized_value in {item.strip() for item in normalized_pattern.split("|") if item.strip()}
        return normalized_value == normalized_pattern

    def _load_sources(self, *, workspace_root: Path) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        global_hooks = self._load_hook_config(self._global_config_path)
        sources.append(
            {
                "source": "global",
                "path": self._global_config_path,
                "trusted": True,
                "hooks": global_hooks,
            }
        )
        if self._claude_import_bridge is not None:
            self._claude_import_bridge.refresh()
            hook_settings = {}
            try:
                hook_settings = dict(getattr(self._claude_import_bridge, "effective_hook_settings", lambda: {})() or {})
            except Exception:
                hook_settings = {}
            imported_hooks_disabled = bool(hook_settings.get("disable_hooks"))
            project_trusted = self._is_project_trusted(workspace_root)
            if not imported_hooks_disabled:
                for imported in self._claude_import_bridge.imported_hook_sources():
                    source_name = str(imported.source or "").strip()
                    trusted = project_trusted or source_name not in {"claude_project", "claude_local"}
                    if not trusted:
                        continue
                    sources.append(
                        {
                            "source": source_name,
                            "path": Path(imported.path),
                            "trusted": trusted,
                            "hooks": imported.hooks,
                        }
                    )
        project_path = self._project_config_path(workspace_root)
        if project_path.exists() and self._is_project_trusted(workspace_root):
            sources.append(
                {
                    "source": "project",
                    "path": project_path,
                    "trusted": True,
                    "hooks": self._load_hook_config(project_path),
                }
            )
        return sources

    def _load_hook_config(self, path: Path) -> dict[str, list[dict[str, Any]]]:
        payload = read_json(path, {})
        if not isinstance(payload, dict):
            return {}
        raw_hooks = payload.get("hooks")
        if not isinstance(raw_hooks, dict):
            return {}
        hooks: dict[str, list[dict[str, Any]]] = {}
        for event_name, items in raw_hooks.items():
            normalized_event = str(event_name or "").strip()
            if normalized_event not in SUPPORTED_HOOK_EVENTS or not isinstance(items, list):
                continue
            normalized_items: list[dict[str, Any]] = []
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                normalized_items.append(
                    {
                        "hook_id": str(item.get("hook_id") or item.get("id") or f"{normalized_event.lower()}-{index}").strip(),
                        "command": str(item.get("command") or "").strip(),
                        "matcher": str(item.get("matcher") or "*").strip() or "*",
                        "timeout_seconds": max(1, int(item.get("timeout_seconds") or 10)),
                        "enabled": bool(item.get("enabled", True)),
                    }
                )
            hooks[normalized_event] = normalized_items
        return hooks

    def _load_trust_policy(self) -> dict[str, Any]:
        payload = read_json(self._trust_path, {})
        return payload if isinstance(payload, dict) else {}

    def _is_project_trusted(self, workspace_root: Path) -> bool:
        return str(workspace_root) in set(self.trusted_project_roots())

    def _resolve_workspace_root(self, workspace_root: Path | str | None) -> Path:
        if workspace_root is None:
            return self._root_dir
        return Path(str(workspace_root)).expanduser().resolve()

    @staticmethod
    def _project_config_path(workspace_root: Path) -> Path:
        return (workspace_root / ".agora" / "hooks.json").resolve()

    @staticmethod
    def _event(event: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "event": str(event or "").strip(),
            "payload": dict(payload or {}),
            "emitted_at": now_iso(),
        }
