from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import plistlib
import re
from typing import Any

import json
import yaml


_CLAUDE_MACOS_PREFERENCE_DOMAIN = "com.anthropic.claudecode"
_CLAUDE_WINDOWS_REGISTRY_KEY_PATH_HKLM = r"SOFTWARE\Policies\ClaudeCode"
_CLAUDE_WINDOWS_REGISTRY_KEY_PATH_HKCU = r"SOFTWARE\Policies\ClaudeCode"
_CLAUDE_WINDOWS_REGISTRY_VALUE_NAME = "Settings"


def _slugify(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "-").replace("_", "-")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    content = str(text or "")
    if not content.startswith("---\n"):
        return {}, content
    marker = "\n---\n"
    end_index = content.find(marker, 4)
    if end_index < 0:
        return {}, content
    raw_frontmatter = content[4:end_index]
    body = content[end_index + len(marker) :]
    try:
        payload = yaml.safe_load(raw_frontmatter) or {}
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}, body


def _first_nonempty_line(text: str) -> str:
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line:
            return line
    return ""


def _coerce_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _find_first_unescaped_char(text: str, char: str) -> int:
    for index, current in enumerate(text):
        if current != char:
            continue
        backslash_count = 0
        probe = index - 1
        while probe >= 0 and text[probe] == "\\":
            backslash_count += 1
            probe -= 1
        if backslash_count % 2 == 0:
            return index
    return -1


def _find_last_unescaped_char(text: str, char: str) -> int:
    for index in range(len(text) - 1, -1, -1):
        if text[index] != char:
            continue
        backslash_count = 0
        probe = index - 1
        while probe >= 0 and text[probe] == "\\":
            backslash_count += 1
            probe -= 1
        if backslash_count % 2 == 0:
            return index
    return -1


def _unescape_rule_content(text: str) -> str:
    return str(text or "").replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")


def _parse_permission_rule(rule: str) -> tuple[str, str]:
    raw = str(rule or "").strip()
    if not raw:
        return "", ""
    open_index = _find_first_unescaped_char(raw, "(")
    if open_index < 0:
        return raw, ""
    close_index = _find_last_unescaped_char(raw, ")")
    if close_index <= open_index or close_index != len(raw) - 1:
        return raw, ""
    tool_name = str(raw[:open_index] or "").strip()
    raw_content = raw[open_index + 1 : close_index]
    if not tool_name:
        return raw, ""
    if raw_content in {"", "*"}:
        return tool_name, ""
    return tool_name, _unescape_rule_content(raw_content)


def _permission_rule_extract_prefix(rule_content: str) -> str | None:
    match = re.fullmatch(r"(.+):\*", str(rule_content or ""))
    return str(match.group(1) or "") if match else None


def _has_wildcards(pattern: str) -> bool:
    text = str(pattern or "")
    if text.endswith(":*"):
        return False
    for index, current in enumerate(text):
        if current != "*":
            continue
        backslash_count = 0
        probe = index - 1
        while probe >= 0 and text[probe] == "\\":
            backslash_count += 1
            probe -= 1
        if backslash_count % 2 == 0:
            return True
    return False


def _match_wildcard_pattern(pattern: str, command: str) -> bool:
    trimmed = str(pattern or "").strip()
    if not trimmed:
        return False
    escaped_star_placeholder = "\x00ESCAPED_STAR\x00"
    escaped_backslash_placeholder = "\x00ESCAPED_BACKSLASH\x00"
    processed: list[str] = []
    index = 0
    while index < len(trimmed):
        current = trimmed[index]
        if current == "\\" and index + 1 < len(trimmed):
            next_char = trimmed[index + 1]
            if next_char == "*":
                processed.append(escaped_star_placeholder)
                index += 2
                continue
            if next_char == "\\":
                processed.append(escaped_backslash_placeholder)
                index += 2
                continue
        processed.append(current)
        index += 1
    processed_text = "".join(processed)
    regex_pattern = re.escape(processed_text).replace(r"\*", ".*")
    regex_pattern = regex_pattern.replace(re.escape(escaped_star_placeholder), r"\*")
    regex_pattern = regex_pattern.replace(re.escape(escaped_backslash_placeholder), r"\\")
    if regex_pattern.endswith(r"\ .*") and processed_text.count("*") == 1:
        regex_pattern = regex_pattern[: -len(r"\ .*")] + r"( .*)?"
    return bool(re.fullmatch(regex_pattern, str(command or ""), flags=re.DOTALL))


def _match_shell_permission_rule(rule_content: str, command_text: str) -> bool:
    candidate = str(command_text or "").strip()
    pattern = str(rule_content or "").strip()
    if not candidate or not pattern:
        return False
    prefix = _permission_rule_extract_prefix(pattern)
    if prefix is not None:
        return candidate == prefix or candidate.startswith(prefix + " ")
    if _has_wildcards(pattern):
        return _match_wildcard_pattern(pattern, candidate)
    return candidate == pattern


def _path_candidates_for_rule_match(
    *,
    payload: dict[str, Any],
    workspace_root: Path | None,
    fallback_root: Path,
) -> list[str]:
    values: list[str] = []
    for key in ("path", "target_path", "cwd"):
        candidate = str(payload.get(key) or "").strip()
        if candidate:
            values.append(candidate)
    normalized: list[str] = []
    seen: set[str] = set()
    anchors = [item for item in (workspace_root, fallback_root) if item is not None]
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser()
        resolved = path.resolve() if path.is_absolute() else None
        variants: list[str] = []
        if resolved is not None:
            variants.append(str(resolved))
            for anchor in anchors:
                try:
                    variants.append(str(resolved.relative_to(anchor)).replace("\\", "/"))
                except Exception:
                    continue
        else:
            variants.append(text.replace("\\", "/"))
        for item in variants:
            normalized_item = str(item or "").strip()
            if normalized_item and normalized_item not in seen:
                seen.add(normalized_item)
                normalized.append(normalized_item)
    return normalized


def _match_path_glob(pattern: str, candidate_paths: list[str]) -> bool:
    glob = str(pattern or "").strip()
    if not glob:
        return False
    return any(fnmatch.fnmatch(str(item or ""), glob) for item in candidate_paths)


def _merge_unique_list(values: list[Any], incoming: list[Any]) -> list[Any]:
    merged: list[Any] = []
    seen: set[str] = set()
    for item in [*list(values or []), *list(incoming or [])]:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(item)
    return merged


def _merge_settings_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in dict(overlay or {}).items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_settings_dict(existing, value)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            merged[key] = _merge_unique_list(existing, value)
            continue
        merged[key] = value
    return merged


def _normalize_permission_mode(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"default", "ask"}:
        return ""
    if raw in {"readonly", "read_only"}:
        return "readonly"
    if raw == "plan":
        return "plan"
    if raw == "auto":
        return "auto"
    if raw in {"acceptedits", "dontask", "bypasspermissions", "bypass_permissions", "bypass", "full_access"}:
        return "bypass"
    return raw


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class ImportedClaudeAgent:
    agent_id: str
    title: str
    description: str
    prompt: str
    tools: tuple[str, ...]
    default_access_mode: str
    worktree_mode: str
    supports_background: bool
    source_path: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "title": self.title,
            "description": self.description,
            "prompt": self.prompt,
            "tools": list(self.tools),
            "default_access_mode": self.default_access_mode,
            "worktree_mode": self.worktree_mode,
            "supports_background": self.supports_background,
            "source": "claude_import",
            "source_path": self.source_path,
        }


@dataclass(frozen=True)
class ImportedClaudeCommand:
    command_id: str
    title: str
    description: str
    usage: str
    prompt: str
    argument_hint: str
    source_path: str
    aliases: tuple[str, ...] = ()

    def model_dump(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "title": self.title,
            "description": self.description,
            "usage": self.usage,
            "aliases": list(self.aliases),
            "source": "claude_import",
            "source_path": self.source_path,
            "argument_hint": self.argument_hint,
            "prompt_preview": _first_nonempty_line(self.prompt),
        }


@dataclass(frozen=True)
class ImportedClaudeHookSource:
    source: str
    path: str
    hooks: dict[str, list[dict[str, Any]]]
    permissions: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        hook_count = sum(len(list(items or [])) for items in self.hooks.values())
        return {
            "source": self.source,
            "path": self.path,
            "hook_count": hook_count,
            "events": {key: len(list(items or [])) for key, items in self.hooks.items()},
            "permissions": self.permissions,
        }


@dataclass(frozen=True)
class ImportedClaudePermissionRule:
    source: str
    path: str
    effect: str
    raw_rule: str
    tool_name: str
    rule_content: str

    def model_dump(self) -> dict[str, Any]:
        summary = self.tool_name
        if self.rule_content:
            summary = f"{summary}({self.rule_content})"
        return {
            "source": self.source,
            "path": self.path,
            "effect": self.effect,
            "raw_rule": self.raw_rule,
            "tool_name": self.tool_name,
            "rule_content": self.rule_content,
            "summary": summary,
        }


@dataclass(frozen=True)
class ImportedClaudeInstructionFile:
    source: str
    path: str
    relative_path: str
    directory: str
    priority: int
    text: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
            "relative_path": self.relative_path,
            "directory": self.directory,
            "priority": self.priority,
            "char_count": len(self.text),
            "preview": _first_nonempty_line(self.text),
        }


@dataclass(frozen=True)
class ImportedClaudeSettingsSource:
    source: str
    layer: str
    path: str
    provider: str
    provider_label: str
    settings: dict[str, Any]
    hooks: dict[str, list[dict[str, Any]]]
    permissions: dict[str, Any]
    permission_rules: tuple[ImportedClaudePermissionRule, ...]
    default_mode: str
    additional_directories: tuple[str, ...]
    claude_md_excludes: tuple[str, ...]
    disable_auto_mode: str
    disable_bypass_permissions_mode: str
    unsupported_keys: tuple[str, ...]

    def model_dump(self) -> dict[str, Any]:
        hook_count = sum(len(list(items or [])) for items in self.hooks.values())
        return {
            "source": self.source,
            "layer": self.layer,
            "path": self.path,
            "provider": self.provider,
            "provider_label": self.provider_label,
            "settings": self.settings,
            "hook_count": hook_count,
            "events": {key: len(list(items or [])) for key, items in self.hooks.items()},
            "permissions": self.permissions,
            "default_mode": self.default_mode,
            "additional_directories": list(self.additional_directories),
            "claude_md_excludes": list(self.claude_md_excludes),
            "disable_auto_mode": self.disable_auto_mode,
            "disable_bypass_permissions_mode": self.disable_bypass_permissions_mode,
            "unsupported_keys": list(self.unsupported_keys),
            "permission_rule_count": len(self.permission_rules),
            "permission_rules": [item.model_dump() for item in self.permission_rules],
        }


class ClaudeProjectImportBridge:
    _SETTINGS_SOURCE_ORDER = (
        "claude_user",
        "claude_project",
        "claude_local",
        "claude_flag",
        "claude_policy",
    )

    def __init__(
        self,
        *,
        root_dir: Path,
        user_settings_path: Path | None = None,
        flag_settings: dict[str, Any] | None = None,
        policy_settings: dict[str, Any] | None = None,
    ) -> None:
        self._root_dir = root_dir.resolve()
        self._user_settings_path_override = Path(user_settings_path).expanduser().resolve() if user_settings_path is not None else None
        self._flag_settings_override = dict(flag_settings or {})
        self._policy_settings_override = dict(policy_settings or {})
        self.refresh()

    def refresh(self) -> None:
        self._claude_md_path = (self._root_dir / "CLAUDE.md").resolve()
        self._dot_claude_md_path = (self._root_dir / ".claude" / "CLAUDE.md").resolve()
        self._claude_dir = (self._root_dir / ".claude").resolve()
        self._agents_dir = (self._claude_dir / "agents").resolve()
        self._commands_dir = (self._claude_dir / "commands").resolve()
        self._user_settings_path = self._resolve_user_settings_path()
        self._settings_path = (self._claude_dir / "settings.json").resolve()
        self._settings_local_path = (self._claude_dir / "settings.local.json").resolve()
        self._flag_settings_path = self._resolve_optional_env_path("AGORA_CLAUDE_FLAG_SETTINGS_PATH")
        self._policy_settings_path = self._resolve_optional_env_path("AGORA_CLAUDE_POLICY_SETTINGS_PATH")
        self._remote_managed_settings_path = self._resolve_optional_env_path("AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_PATH")
        self._policy_hklm_settings_path = self._resolve_optional_env_path("AGORA_CLAUDE_POLICY_HKLM_SETTINGS_PATH")
        self._policy_hkcu_settings_path = self._resolve_optional_env_path("AGORA_CLAUDE_POLICY_HKCU_SETTINGS_PATH")
        self._mdm_plist_override_paths = self._resolve_optional_env_paths("AGORA_CLAUDE_MDM_PLIST_PATHS")
        if not self._mdm_plist_override_paths:
            mdm_single_path = self._resolve_optional_env_path("AGORA_CLAUDE_MDM_SETTINGS_PATH")
            if mdm_single_path is not None:
                self._mdm_plist_override_paths = [mdm_single_path]
        self._default_remote_managed_settings_path = (self._root_dir / "config" / "remote-managed-settings.json").resolve()
        self._managed_policy_settings_path = (self._root_dir / "config" / "managed-settings.json").resolve()
        self._managed_policy_dropin_dir = (self._root_dir / "config" / "managed-settings.d").resolve()
        self._claude_md_text = self._read_text(self._claude_md_path)
        self._agents = self._load_agents()
        self._commands = self._load_commands()
        self._settings_sources = self._load_settings_sources()
        self._hook_sources = self._load_hook_sources()
        self._permission_rules = [item for source in self._settings_sources for item in source.permission_rules]
        self._effective_settings = self._build_effective_settings()

    @property
    def claude_md_text(self) -> str:
        return self._claude_md_text

    @property
    def claude_md_path(self) -> Path:
        return self._claude_md_path

    def imported_agents(self) -> list[ImportedClaudeAgent]:
        return list(self._agents)

    def imported_commands(self) -> list[ImportedClaudeCommand]:
        return list(self._commands)

    def imported_hook_sources(self) -> list[ImportedClaudeHookSource]:
        return list(self._hook_sources)

    def imported_settings_sources(self) -> list[ImportedClaudeSettingsSource]:
        return list(self._settings_sources)

    def imported_permission_rules(self) -> list[ImportedClaudePermissionRule]:
        return list(self._permission_rules)

    def imported_claude_md_excludes(self) -> list[str]:
        values = list((self._effective_settings.get("claude_md_excludes") or []))
        return [str(item).strip() for item in values if str(item).strip()]

    def imported_unsupported_settings(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for source in self._settings_sources:
            for item in source.unsupported_keys:
                key = str(item or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    values.append(key)
        return values

    def imported_additional_directories(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for source in self._settings_sources:
            for item in source.additional_directories:
                if item not in seen:
                    seen.add(item)
                    values.append(item)
        return values

    def effective_settings(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._effective_settings))

    def effective_permissions(self) -> dict[str, Any]:
        permissions = self._effective_settings.get("permissions")
        return dict(permissions) if isinstance(permissions, dict) else {}

    def effective_model(self) -> str:
        return str(self._effective_settings.get("model") or "").strip()

    def effective_env(self) -> dict[str, str]:
        payload = self._effective_settings.get("env")
        return dict(payload) if isinstance(payload, dict) else {}

    def effective_cleanup_period_days(self) -> int | None:
        value = self._effective_settings.get("cleanup_period_days")
        try:
            return int(value) if value is not None else None
        except Exception:
            return None

    def effective_status_line(self) -> dict[str, Any]:
        payload = self._effective_settings.get("status_line")
        return dict(payload) if isinstance(payload, dict) else {}

    def effective_include_co_authored_by(self) -> bool:
        return bool(self._effective_settings.get("include_co_authored_by"))

    def effective_hook_settings(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if "disable_hooks" in self._effective_settings:
            payload["disable_hooks"] = bool(self._effective_settings.get("disable_hooks"))
        if "status_line" in self._effective_settings and isinstance(self._effective_settings.get("status_line"), dict):
            payload["status_line"] = dict(self._effective_settings.get("status_line") or {})
        return payload

    def effective_status_line_meta(self) -> dict[str, Any]:
        for source in reversed(self._settings_sources):
            status_line = source.settings.get("status_line")
            if isinstance(status_line, dict) and status_line:
                return {
                    "source": source.source,
                    "layer": source.layer,
                    "provider": source.provider,
                    "path": source.path,
                    "status_line": dict(status_line),
                }
        return {}

    def effective_policy_source_meta(self) -> dict[str, Any]:
        for source in reversed(self._settings_sources):
            if source.source != "claude_policy":
                continue
            return {
                "source": source.source,
                "layer": source.layer,
                "provider": source.provider,
                "provider_label": source.provider_label,
                "path": source.path,
            }
        return {}

    def settings_support_summary(self) -> dict[str, Any]:
        effective = self.effective_settings()
        policy_source = self.effective_policy_source_meta()
        applied_keys: list[str] = []
        passive_keys: list[str] = []
        for key in (
            "hooks",
            "permissions",
            "claude_md_excludes",
            "model",
            "disable_hooks",
            "env",
            "cleanup_period_days",
            "include_co_authored_by",
            "status_line",
        ):
            if key in effective:
                applied_keys.append(key)
        for key in ("model_type",):
            if key in effective:
                passive_keys.append(key)
        return {
            "applied_keys": applied_keys,
            "passive_keys": passive_keys,
            "unsupported_keys": self.imported_unsupported_settings(),
            "effective_key_count": len(effective),
            "policy_provider": str(policy_source.get("provider") or "").strip(),
        }

    def effective_default_mode_meta(self) -> dict[str, Any]:
        permissions = self.effective_permissions()
        raw_mode = str(permissions.get("default_mode") or "").strip()
        effective_mode = _normalize_permission_mode(raw_mode)
        disabled = False
        disabled_reason = ""
        if effective_mode == "auto" and self._auto_mode_disabled():
            effective_mode = ""
            disabled = True
            disabled_reason = "disable_auto_mode"
        if effective_mode == "bypass" and self._bypass_mode_disabled():
            effective_mode = ""
            disabled = True
            disabled_reason = "disable_bypass_permissions_mode"
        safe_mapping = {
            "plan": "read_only_fence",
            "readonly": "read_only_fence",
            "auto": "safe_read_auto_subset",
            "bypass": "safe_sandbox_write_subset",
        }.get(effective_mode, "")
        return {
            "raw_mode": raw_mode,
            "effective_mode": effective_mode,
            "disabled": disabled,
            "disabled_reason": disabled_reason,
            "disable_auto_mode": self._auto_mode_disabled(),
            "disable_bypass_permissions_mode": self._bypass_mode_disabled(),
            "safe_mapping": safe_mapping,
        }

    def effective_default_mode(self) -> str:
        return str(self.effective_default_mode_meta().get("effective_mode") or "").strip()

    def match_permission_rule(self, *, action: Any) -> dict[str, Any] | None:
        for effect in ("deny", "allow", "ask"):
            rules = [
                rule
                for source_name in self._SETTINGS_SOURCE_ORDER
                for source in self._settings_sources
                if source.source == source_name
                for rule in source.permission_rules
                if rule.effect == effect
            ]
            for rule in reversed(rules):
                if self._permission_rule_matches(rule=rule, action=action):
                    return {
                        **rule.model_dump(),
                        "state_label": "Imported",
                        "match_reason": f"Matched imported Claude rule `{rule.raw_rule}` from {rule.source}.",
                        "enabled": True,
                    }
        return None

    def resolve_instruction_files(
        self,
        *,
        workspace_root: str | Path | None = None,
        target_path: str | Path | None = None,
    ) -> list[ImportedClaudeInstructionFile]:
        target_dir = self._resolve_instruction_target_dir(workspace_root=workspace_root, target_path=target_path)
        anchor_root = self._resolve_instruction_anchor_root(target_dir)
        directories = self._instruction_directories(anchor_root=anchor_root, target_dir=target_dir)
        excludes = self.imported_claude_md_excludes()
        items: list[ImportedClaudeInstructionFile] = []
        seen: set[str] = set()
        priority = 0
        for directory in directories:
            for source_name, candidate in (
                ("claude_project", (directory / "CLAUDE.md").resolve()),
                ("claude_project", (directory / ".claude" / "CLAUDE.md").resolve()),
            ):
                text = self._read_text(candidate)
                if not text or str(candidate) in seen or self._is_instruction_path_excluded(candidate, patterns=excludes):
                    continue
                seen.add(str(candidate))
                priority += 1
                try:
                    relative_path = str(candidate.relative_to(anchor_root)).replace("\\", "/")
                except Exception:
                    relative_path = candidate.name
                items.append(
                    ImportedClaudeInstructionFile(
                        source=source_name,
                        path=str(candidate),
                        relative_path=relative_path,
                        directory=str(directory),
                        priority=priority,
                        text=text,
                    )
                )
        return items

    def build_runtime_instruction_context(
        self,
        *,
        max_chars: int = 4000,
        workspace_root: str | Path | None = None,
        target_path: str | Path | None = None,
    ) -> str:
        instruction_files = self.resolve_instruction_files(workspace_root=workspace_root, target_path=target_path)
        if not instruction_files:
            return ""
        lines = [
            "Imported Claude instruction hierarchy:",
            "- Earlier files are broader workspace guidance.",
            "- Later files are closer to the active workspace and take precedence.",
        ]
        remaining_budget = max(0, int(max_chars or 0))
        omitted_count = 0
        for item in instruction_files:
            block = f"### {item.relative_path}\n{item.text.strip()}".strip()
            if remaining_budget > 0 and len(block) > remaining_budget:
                block = block[: max(0, remaining_budget - 16)].rstrip() + "\n...[truncated]"
            if remaining_budget <= 0:
                omitted_count += 1
                continue
            lines.extend(["", block])
            remaining_budget = max(0, remaining_budget - len(block))
        if omitted_count > 0:
            lines.extend(["", f"[{omitted_count} additional Claude instruction file(s) omitted due to budget.]"])
        return "\n\n".join(lines).strip()

    def build_report(self) -> dict[str, Any]:
        instruction_files = self.resolve_instruction_files()
        default_mode_meta = self.effective_default_mode_meta()
        return {
            "workspace_root": str(self._root_dir),
            "files_present": {
                "user_settings": self._user_settings_path.exists(),
                "CLAUDE.md": self._claude_md_path.exists(),
                ".claude/CLAUDE.md": self._dot_claude_md_path.exists(),
                ".claude/agents": self._agents_dir.exists(),
                ".claude/commands": self._commands_dir.exists(),
                ".claude/settings.json": self._settings_path.exists(),
                ".claude/settings.local.json": self._settings_local_path.exists(),
                "flag_settings": bool(self._flag_settings_override) or bool(str(os.getenv("AGORA_CLAUDE_FLAG_SETTINGS_JSON", "")).strip()) or (self._flag_settings_path.exists() if self._flag_settings_path is not None else False),
                "policy_settings": bool(self._policy_settings_override)
                or bool(str(os.getenv("AGORA_CLAUDE_POLICY_SETTINGS_JSON", "")).strip())
                or (self._policy_settings_path.exists() if self._policy_settings_path is not None else False)
                or self._managed_policy_settings_path.exists()
                or self._managed_policy_dropin_dir.exists(),
                "remote_managed_settings": bool(str(os.getenv("AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_JSON", "")).strip())
                or (self._remote_managed_settings_path.exists() if self._remote_managed_settings_path is not None else False)
                or self._default_remote_managed_settings_path.exists(),
                "mdm_policy_settings": bool(str(os.getenv("AGORA_CLAUDE_MDM_SETTINGS_JSON", "")).strip())
                or any(path.exists() for path, _label in self._macos_mdm_plist_candidates()),
                "registry_hklm_policy_settings": bool(str(os.getenv("AGORA_CLAUDE_POLICY_HKLM_SETTINGS_JSON", "")).strip())
                or (self._policy_hklm_settings_path.exists() if self._policy_hklm_settings_path is not None else False),
                "registry_hkcu_policy_settings": bool(str(os.getenv("AGORA_CLAUDE_POLICY_HKCU_SETTINGS_JSON", "")).strip())
                or (self._policy_hkcu_settings_path.exists() if self._policy_hkcu_settings_path is not None else False),
            },
            "claude_md": {
                "path": str(self._claude_md_path),
                "present": self._claude_md_path.exists(),
                "char_count": len(self._claude_md_text),
                "preview": _first_nonempty_line(self._claude_md_text),
            },
            "agents": [item.model_dump() for item in self._agents],
            "commands": [item.model_dump() for item in self._commands],
            "hook_sources": [item.model_dump() for item in self._hook_sources],
            "settings_sources": [item.model_dump() for item in self._settings_sources],
            "permission_rules": [item.model_dump() for item in self._permission_rules],
            "instruction_files": [item.model_dump() for item in instruction_files],
            "effective_settings": self.effective_settings(),
            "effective_permissions": self.effective_permissions(),
            "effective_policy_source": self.effective_policy_source_meta(),
            "default_mode_meta": default_mode_meta,
            "claude_md_excludes": self.imported_claude_md_excludes(),
            "settings_support": self.settings_support_summary(),
            "settings_source_order": list(self._SETTINGS_SOURCE_ORDER),
            "summary": {
                "agent_count": len(self._agents),
                "command_count": len(self._commands),
                "hook_source_count": len(self._hook_sources),
                "hook_count": sum(sum(len(list(items or [])) for items in source.hooks.values()) for source in self._hook_sources),
                "settings_source_count": len(self._settings_sources),
                "permission_rule_count": len(self._permission_rules),
                "additional_directory_count": len(self.imported_additional_directories()),
                "instruction_file_count": len(instruction_files),
                "claude_md_exclude_count": len(self.imported_claude_md_excludes()),
                "unsupported_settings_count": len(self.imported_unsupported_settings()),
            },
            "effective_default_mode": str(default_mode_meta.get("effective_mode") or ""),
            "additional_directories": self.imported_additional_directories(),
        }

    def _build_effective_settings(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for source_name in self._SETTINGS_SOURCE_ORDER:
            source = next((item for item in self._settings_sources if item.source == source_name), None)
            if source is None:
                continue
            merged = _merge_settings_dict(merged, source.settings)
        return merged

    def _auto_mode_disabled(self) -> bool:
        effective = self._effective_settings
        top_level = str(effective.get("disable_auto_mode") or "").strip().lower()
        permissions = self.effective_permissions()
        nested = str(permissions.get("disable_auto_mode") or "").strip().lower()
        return top_level == "disable" or nested == "disable"

    def _bypass_mode_disabled(self) -> bool:
        permissions = self.effective_permissions()
        return str(permissions.get("disable_bypass_permissions_mode") or "").strip().lower() == "disable"

    def _resolve_instruction_target_dir(
        self,
        *,
        workspace_root: str | Path | None = None,
        target_path: str | Path | None = None,
    ) -> Path:
        raw = target_path if target_path is not None else workspace_root
        if raw is None or not str(raw).strip():
            return self._root_dir
        candidate = Path(str(raw)).expanduser()
        resolved = candidate.resolve()
        if candidate.exists() and candidate.is_file():
            return resolved.parent
        if resolved.suffix and not candidate.exists():
            return resolved.parent
        return resolved

    def _resolve_instruction_anchor_root(self, target_dir: Path) -> Path:
        candidate_roots = [self._root_dir, *[Path(item).expanduser().resolve() for item in self.imported_additional_directories()]]
        eligible = [item for item in candidate_roots if _path_is_relative_to(target_dir, item)]
        if not eligible:
            return self._root_dir
        return max(eligible, key=lambda item: len(str(item)))

    @staticmethod
    def _instruction_directories(*, anchor_root: Path, target_dir: Path) -> list[Path]:
        if not _path_is_relative_to(target_dir, anchor_root):
            return [anchor_root]
        directories: list[Path] = []
        current = target_dir
        while True:
            directories.append(current)
            if current == anchor_root:
                break
            current = current.parent
        return list(reversed(directories))

    def _is_instruction_path_excluded(self, path: Path, *, patterns: list[str]) -> bool:
        absolute = str(path.resolve()).replace("\\", "/")
        try:
            relative = str(path.resolve().relative_to(self._root_dir)).replace("\\", "/")
        except Exception:
            relative = ""
        return any(
            fnmatch.fnmatch(absolute, str(pattern or "").strip())
            or (relative and fnmatch.fnmatch(relative, str(pattern or "").strip()))
            for pattern in patterns
            if str(pattern or "").strip()
        )

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_agents(self) -> list[ImportedClaudeAgent]:
        if not self._agents_dir.exists():
            return []
        items: list[ImportedClaudeAgent] = []
        for path in sorted(self._agents_dir.glob("*.md")):
            text = self._read_text(path)
            frontmatter, body = _split_frontmatter(text)
            agent_id = _slugify(frontmatter.get("name") or path.stem)
            if not agent_id:
                continue
            title = str(frontmatter.get("name") or path.stem).strip() or path.stem
            description = str(frontmatter.get("description") or "").strip()
            prompt = str(body or "").strip()
            tools = tuple(_coerce_list(frontmatter.get("tools")) or ["*"])
            permission_mode = str(frontmatter.get("permissionMode") or frontmatter.get("permission_mode") or "").strip().lower()
            if permission_mode in {"plan", "readonly"}:
                default_access_mode = "chat_only"
            elif permission_mode in {"bypasspermissions", "bypass_permissions", "full_access"}:
                default_access_mode = "full_access"
            else:
                default_access_mode = "sandboxed"
            isolation = str(frontmatter.get("isolation") or "").strip().lower()
            worktree_mode = "isolated" if isolation == "worktree" else "shared"
            supports_background = bool(frontmatter.get("background", True))
            items.append(
                ImportedClaudeAgent(
                    agent_id=agent_id,
                    title=title,
                    description=description,
                    prompt=prompt,
                    tools=tools,
                    default_access_mode=default_access_mode,
                    worktree_mode=worktree_mode,
                    supports_background=supports_background,
                    source_path=str(path),
                )
            )
        return items

    def _load_commands(self) -> list[ImportedClaudeCommand]:
        if not self._commands_dir.exists():
            return []
        items: list[ImportedClaudeCommand] = []
        for path in sorted(self._commands_dir.rglob("*.md")):
            if not path.is_file():
                continue
            text = self._read_text(path)
            frontmatter, body = _split_frontmatter(text)
            command_id = _slugify(frontmatter.get("name") or path.stem)
            if not command_id:
                continue
            title = str(frontmatter.get("name") or path.stem).strip() or path.stem
            description = str(frontmatter.get("description") or _first_nonempty_line(body) or "").strip()
            argument_hint = str(frontmatter.get("argument-hint") or frontmatter.get("argument_hint") or "").strip()
            usage = f"/{command_id}" if not argument_hint else f"/{command_id} {argument_hint}"
            aliases = tuple(_slugify(item) for item in _coerce_list(frontmatter.get("aliases")) if _slugify(item))
            items.append(
                ImportedClaudeCommand(
                    command_id=command_id,
                    title=title,
                    description=description,
                    usage=usage,
                    prompt=str(body or "").strip(),
                    argument_hint=argument_hint,
                    source_path=str(path),
                    aliases=aliases,
                )
            )
        return items

    def _load_settings_sources(self) -> list[ImportedClaudeSettingsSource]:
        items: list[ImportedClaudeSettingsSource] = []
        user_source = self._load_settings_source_from_payload(
            source_name="claude_user",
            layer="user",
            path=self._user_settings_path,
            payload=self._read_json(self._user_settings_path),
            settings_root=self._user_settings_path.parent.parent if self._user_settings_path.parent.name == ".claude" else self._user_settings_path.parent,
        )
        if user_source is not None:
            items.append(user_source)
        for source_name, layer, path in (
            ("claude_project", "project", self._settings_path),
            ("claude_local", "local", self._settings_local_path),
        ):
            source = self._load_settings_source_from_payload(
                source_name=source_name,
                layer=layer,
                path=path,
                payload=self._read_json(path),
                settings_root=self._root_dir,
            )
            if source is not None:
                items.append(source)
        flag_source = self._load_flag_settings_source()
        if flag_source is not None:
            items.append(flag_source)
        policy_source = self._load_policy_settings_source()
        if policy_source is not None:
            items.append(policy_source)
        return items

    def _load_settings_source_from_payload(
        self,
        *,
        source_name: str,
        layer: str,
        path: Path | None,
        payload: dict[str, Any],
        settings_root: Path,
        provider: str | None = None,
        provider_label: str | None = None,
    ) -> ImportedClaudeSettingsSource | None:
        if not payload:
            return None
        settings, unsupported_keys = self._normalize_settings_payload(payload)
        hooks = dict(settings.get("hooks") or {}) if isinstance(settings.get("hooks"), dict) else {}
        permissions = dict(settings.get("permissions") or {}) if isinstance(settings.get("permissions"), dict) else {}
        disable_auto_mode = str(settings.get("disable_auto_mode") or "").strip().lower()
        claude_md_excludes = tuple(
            str(item).strip()
            for item in list(settings.get("claude_md_excludes") or [])
            if str(item).strip()
        )
        default_mode = str(permissions.get("default_mode") or "").strip()
        additional_directories = tuple(
            self._normalize_additional_directories(payload.get("permissions"), settings_root=settings_root)
        )
        permission_rules = tuple(
            self._normalize_permission_rules(permissions=permissions, source=source_name, path=path or settings_root)
        )
        if not settings and not additional_directories and not unsupported_keys:
            return None
        return ImportedClaudeSettingsSource(
            source=source_name,
            layer=layer,
            path=str(path or settings_root),
            provider=str(provider or source_name).strip(),
            provider_label=str(provider_label or path or settings_root).strip(),
            settings=settings,
            hooks=hooks,
            permissions=permissions,
            permission_rules=permission_rules,
            default_mode=default_mode,
            additional_directories=additional_directories,
            claude_md_excludes=claude_md_excludes,
            disable_auto_mode=disable_auto_mode,
            disable_bypass_permissions_mode=str(permissions.get("disable_bypass_permissions_mode") or "").strip().lower(),
            unsupported_keys=unsupported_keys,
        )

    def _load_flag_settings_source(self) -> ImportedClaudeSettingsSource | None:
        payload = dict(self._flag_settings_override)
        source_path = self._flag_settings_path
        if not payload:
            inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_FLAG_SETTINGS_JSON", ""))
            if inline_payload:
                payload = inline_payload
                source_path = None
        if not payload and source_path is not None:
            payload = self._read_json(source_path)
        if not payload:
            return None
        settings_root = source_path.parent if source_path is not None else self._root_dir
        source_label = source_path if source_path is not None else (self._root_dir / "env:AGORA_CLAUDE_FLAG_SETTINGS_JSON")
        return self._load_settings_source_from_payload(
            source_name="claude_flag",
            layer="flag",
            path=source_label,
            payload=payload,
            settings_root=settings_root,
        )

    def _load_policy_settings_source(self) -> ImportedClaudeSettingsSource | None:
        payload = dict(self._policy_settings_override)
        source_label: Path | None = None
        provider = "override"
        provider_label = "override:claude_policy_settings"
        if payload:
            source_label = self._root_dir / "override:claude_policy_settings"
        if not payload:
            inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_POLICY_SETTINGS_JSON", ""))
            if inline_payload:
                payload = inline_payload
                source_label = self._root_dir / "env:AGORA_CLAUDE_POLICY_SETTINGS_JSON"
                provider = "override"
                provider_label = "env:AGORA_CLAUDE_POLICY_SETTINGS_JSON"
        if not payload and self._policy_settings_path is not None:
            file_payload = self._read_json(self._policy_settings_path)
            if file_payload:
                payload = file_payload
                source_label = self._policy_settings_path
                provider = "override"
                provider_label = "env:AGORA_CLAUDE_POLICY_SETTINGS_PATH"
        if not payload:
            remote_payload, remote_path, remote_label = self._load_remote_managed_policy_settings()
            if remote_payload:
                payload = remote_payload
                source_label = remote_path
                provider = "remote_managed"
                provider_label = remote_label
        if not payload:
            admin_payload, admin_path, admin_provider, admin_label = self._load_admin_policy_settings()
            if admin_payload:
                payload = admin_payload
                source_label = admin_path
                provider = admin_provider
                provider_label = admin_label
        if not payload:
            managed_payload = self._load_managed_policy_settings()
            if managed_payload:
                payload = managed_payload
                source_label = self._managed_policy_settings_path
                provider = "managed_file"
                provider_label = "managed-settings.json"
        if not payload:
            hkcu_payload, hkcu_path, hkcu_label = self._load_hkcu_policy_settings()
            if hkcu_payload:
                payload = hkcu_payload
                source_label = hkcu_path
                provider = "registry_hkcu"
                provider_label = hkcu_label
        if not payload:
            return None
        return self._load_settings_source_from_payload(
            source_name="claude_policy",
            layer="policy",
            path=source_label,
            payload=payload,
            settings_root=self._root_dir,
            provider=provider,
            provider_label=provider_label,
        )

    def _load_hook_sources(self) -> list[ImportedClaudeHookSource]:
        return [
            ImportedClaudeHookSource(
                source=source.source,
                path=source.path,
                hooks=source.hooks,
                permissions=source.permissions,
            )
            for source in self._settings_sources
            if source.hooks or source.permissions
        ]

    @staticmethod
    def _normalize_hooks(raw_hooks: Any) -> dict[str, list[dict[str, Any]]]:
        if not isinstance(raw_hooks, dict):
            return {}
        hooks: dict[str, list[dict[str, Any]]] = {}
        supported = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop", "Notification"}
        for event_name, entries in raw_hooks.items():
            normalized_event = str(event_name or "").strip()
            if normalized_event not in supported or not isinstance(entries, list):
                continue
            normalized_entries: list[dict[str, Any]] = []
            for index, entry in enumerate(entries, start=1):
                if not isinstance(entry, dict):
                    continue
                matcher = str(entry.get("matcher") or "*").strip() or "*"
                nested_hooks = entry.get("hooks")
                if isinstance(nested_hooks, list):
                    for nested_index, nested in enumerate(nested_hooks, start=1):
                        if not isinstance(nested, dict) or str(nested.get("type") or "").strip() not in {"", "command"}:
                            continue
                        command = str(nested.get("command") or "").strip()
                        if not command:
                            continue
                        normalized_entries.append(
                            {
                                "hook_id": str(entry.get("hook_id") or f"{normalized_event.lower()}-{index}-{nested_index}"),
                                "command": command,
                                "matcher": matcher,
                                "timeout_seconds": max(1, int(nested.get("timeout") or nested.get("timeout_seconds") or 10)),
                                "enabled": bool(nested.get("enabled", True)),
                            }
                        )
                    continue
                command = str(entry.get("command") or "").strip()
                if not command:
                    continue
                normalized_entries.append(
                    {
                        "hook_id": str(entry.get("hook_id") or f"{normalized_event.lower()}-{index}"),
                        "command": command,
                        "matcher": matcher,
                        "timeout_seconds": max(1, int(entry.get("timeout") or entry.get("timeout_seconds") or 10)),
                        "enabled": bool(entry.get("enabled", True)),
                    }
                )
            if normalized_entries:
                hooks[normalized_event] = normalized_entries
        return hooks

    @staticmethod
    def _normalize_permissions(raw_permissions: Any) -> dict[str, Any]:
        if not isinstance(raw_permissions, dict):
            return {}
        payload: dict[str, Any] = {}
        for field in ("allow", "ask", "deny"):
            values = [str(item).strip() for item in list(raw_permissions.get(field) or []) if str(item).strip()]
            if values:
                payload[field] = values
        default_mode = str(raw_permissions.get("defaultMode") or raw_permissions.get("default_mode") or "").strip()
        if default_mode:
            payload["default_mode"] = default_mode
        disable_bypass = str(
            raw_permissions.get("disableBypassPermissionsMode") or raw_permissions.get("disable_bypass_permissions_mode") or ""
        ).strip().lower()
        if disable_bypass:
            payload["disable_bypass_permissions_mode"] = disable_bypass
        disable_auto = str(raw_permissions.get("disableAutoMode") or raw_permissions.get("disable_auto_mode") or "").strip().lower()
        if disable_auto:
            payload["disable_auto_mode"] = disable_auto
        additional_directories = [
            str(item).strip()
            for item in list(raw_permissions.get("additionalDirectories") or raw_permissions.get("additional_directories") or [])
            if str(item).strip()
        ]
        if additional_directories:
            payload["additional_directories"] = additional_directories
        return payload

    @staticmethod
    def _normalize_env(raw_env: Any) -> dict[str, str]:
        if not isinstance(raw_env, dict):
            return {}
        payload: dict[str, str] = {}
        for key, value in raw_env.items():
            name = str(key or "").strip()
            if not name:
                continue
            payload[name] = str(value)
        return payload

    @staticmethod
    def _normalize_status_line(raw_status_line: Any) -> dict[str, Any]:
        if not isinstance(raw_status_line, dict):
            return {}
        line_type = str(raw_status_line.get("type") or "").strip().lower()
        command = str(raw_status_line.get("command") or "").strip()
        if line_type not in {"", "command"} or not command:
            return {}
        payload: dict[str, Any] = {
            "type": line_type or "command",
            "command": command,
        }
        if "enabled" in raw_status_line:
            payload["enabled"] = bool(raw_status_line.get("enabled"))
        return payload

    def _normalize_settings_payload(self, raw_settings: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
        payload: dict[str, Any] = {}
        handled_keys: set[str] = set()

        hooks = self._normalize_hooks(raw_settings.get("hooks"))
        if hooks:
            payload["hooks"] = hooks
        handled_keys.add("hooks")

        permissions = self._normalize_permissions(raw_settings.get("permissions"))
        if permissions:
            payload["permissions"] = permissions
        handled_keys.add("permissions")

        claude_md_excludes = self._normalize_claude_md_excludes(
            raw_settings.get("claudeMdExcludes") or raw_settings.get("claude_md_excludes")
        )
        if claude_md_excludes:
            payload["claude_md_excludes"] = claude_md_excludes
        handled_keys.update({"claudeMdExcludes", "claude_md_excludes"})

        disable_auto_mode = str(raw_settings.get("disableAutoMode") or raw_settings.get("disable_auto_mode") or "").strip().lower()
        if disable_auto_mode:
            payload["disable_auto_mode"] = disable_auto_mode
        handled_keys.update({"disableAutoMode", "disable_auto_mode"})

        model = str(raw_settings.get("model") or "").strip()
        if model:
            payload["model"] = model
        handled_keys.add("model")

        model_type = str(raw_settings.get("modelType") or raw_settings.get("model_type") or "").strip()
        if model_type:
            payload["model_type"] = model_type
        handled_keys.update({"modelType", "model_type"})

        env = self._normalize_env(raw_settings.get("env"))
        if env:
            payload["env"] = env
        handled_keys.add("env")

        if "cleanupPeriodDays" in raw_settings or "cleanup_period_days" in raw_settings:
            raw_cleanup = raw_settings.get("cleanupPeriodDays", raw_settings.get("cleanup_period_days"))
            try:
                cleanup_days = int(raw_cleanup)
            except Exception:
                cleanup_days = -1
            if cleanup_days >= 0:
                payload["cleanup_period_days"] = cleanup_days
        handled_keys.update({"cleanupPeriodDays", "cleanup_period_days"})

        if "includeCoAuthoredBy" in raw_settings or "include_co_authored_by" in raw_settings:
            payload["include_co_authored_by"] = bool(
                raw_settings.get("includeCoAuthoredBy", raw_settings.get("include_co_authored_by"))
            )
        handled_keys.update({"includeCoAuthoredBy", "include_co_authored_by"})

        status_line = self._normalize_status_line(raw_settings.get("statusLine") or raw_settings.get("status_line"))
        if status_line:
            payload["status_line"] = status_line
        handled_keys.update({"statusLine", "status_line"})

        if "disableHooks" in raw_settings or "disable_hooks" in raw_settings:
            payload["disable_hooks"] = bool(raw_settings.get("disableHooks", raw_settings.get("disable_hooks")))
        handled_keys.update({"disableHooks", "disable_hooks"})

        unsupported_keys = tuple(
            sorted(
                str(key).strip()
                for key in raw_settings.keys()
                if str(key).strip() and str(key).strip() not in handled_keys
            )
        )
        return payload, unsupported_keys

    @staticmethod
    def _normalize_claude_md_excludes(raw_value: Any) -> list[str]:
        if isinstance(raw_value, list):
            return [str(item).strip() for item in raw_value if str(item).strip()]
        if isinstance(raw_value, str) and raw_value.strip():
            return [raw_value.strip()]
        return []

    def _normalize_permission_rules(
        self,
        *,
        permissions: dict[str, Any],
        source: str,
        path: Path,
    ) -> list[ImportedClaudePermissionRule]:
        items: list[ImportedClaudePermissionRule] = []
        for effect in ("allow", "ask", "deny"):
            for raw_rule in list(permissions.get(effect) or []):
                tool_name, rule_content = _parse_permission_rule(str(raw_rule or ""))
                if not tool_name:
                    continue
                items.append(
                    ImportedClaudePermissionRule(
                        source=source,
                        path=str(path),
                        effect=effect,
                        raw_rule=str(raw_rule),
                        tool_name=tool_name,
                        rule_content=rule_content,
                    )
                )
        return items

    def _normalize_additional_directories(self, raw_permissions: Any, *, settings_root: Path) -> list[str]:
        if not isinstance(raw_permissions, dict):
            return []
        values: list[str] = []
        seen: set[str] = set()
        for raw in list(raw_permissions.get("additionalDirectories") or raw_permissions.get("additional_directories") or []):
            text = str(raw or "").strip()
            if not text:
                continue
            candidate = Path(text).expanduser()
            resolved = candidate.resolve() if candidate.is_absolute() else (settings_root / candidate).resolve()
            if str(resolved) not in seen:
                seen.add(str(resolved))
                values.append(str(resolved))
        return values

    @staticmethod
    def _parse_inline_settings_json(raw_text: str) -> dict[str, Any]:
        text = str(raw_text or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _resolve_optional_env_path(env_name: str) -> Path | None:
        raw = str(os.getenv(env_name, "") or "").strip()
        if not raw:
            return None
        try:
            return Path(raw).expanduser().resolve()
        except Exception:
            return None

    @staticmethod
    def _resolve_optional_env_paths(env_name: str) -> list[Path]:
        raw = str(os.getenv(env_name, "") or "").strip()
        if not raw:
            return []
        values: list[str] = []
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            values = [str(item).strip() for item in parsed if str(item).strip()]
        else:
            values = [part.strip() for part in raw.split(os.pathsep) if part.strip()]
        paths: list[Path] = []
        for item in values:
            try:
                paths.append(Path(item).expanduser().resolve())
            except Exception:
                continue
        return paths

    def _resolve_user_settings_path(self) -> Path:
        if self._user_settings_path_override is not None:
            return self._user_settings_path_override
        env_override = self._resolve_optional_env_path("AGORA_CLAUDE_USER_SETTINGS_PATH")
        if env_override is not None:
            return env_override
        return (self._root_dir / "config" / "claude_user_settings.json").resolve()

    def _load_managed_policy_settings(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        found = False
        base_payload = self._read_json(self._managed_policy_settings_path)
        if base_payload:
            merged = _merge_settings_dict(merged, base_payload)
            found = True
        if self._managed_policy_dropin_dir.exists():
            for path in sorted(self._managed_policy_dropin_dir.glob("*.json")):
                payload = self._read_json(path)
                if not payload:
                    continue
                merged = _merge_settings_dict(merged, payload)
                found = True
        return merged if found else {}

    def _load_remote_managed_policy_settings(self) -> tuple[dict[str, Any], Path | None, str]:
        inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_JSON", ""))
        if inline_payload:
            return inline_payload, self._root_dir / "env:AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_JSON", "env:AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_JSON"
        if self._remote_managed_settings_path is not None:
            payload = self._read_json(self._remote_managed_settings_path)
            if payload:
                return payload, self._remote_managed_settings_path, "env:AGORA_CLAUDE_REMOTE_MANAGED_SETTINGS_PATH"
        default_payload = self._read_json(self._default_remote_managed_settings_path)
        if default_payload:
            return default_payload, self._default_remote_managed_settings_path, "remote-managed-settings.json"
        return {}, None, ""

    def _load_admin_policy_settings(self) -> tuple[dict[str, Any], Path | None, str, str]:
        plist_payload, plist_path, plist_label = self._load_macos_mdm_settings()
        if plist_payload:
            return plist_payload, plist_path, "mdm_plist", plist_label
        hklm_payload, hklm_path, hklm_label = self._load_hklm_policy_settings()
        if hklm_payload:
            return hklm_payload, hklm_path, "registry_hklm", hklm_label
        return {}, None, "", ""

    def _load_macos_mdm_settings(self) -> tuple[dict[str, Any], Path | None, str]:
        candidates = self._macos_mdm_plist_candidates()
        for path, label in candidates:
            payload = self._read_plist(path)
            if payload:
                return payload, path, label
        inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_MDM_SETTINGS_JSON", ""))
        if inline_payload:
            return inline_payload, self._root_dir / "env:AGORA_CLAUDE_MDM_SETTINGS_JSON", "env:AGORA_CLAUDE_MDM_SETTINGS_JSON"
        return {}, None, ""

    def _load_hklm_policy_settings(self) -> tuple[dict[str, Any], Path | None, str]:
        inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_POLICY_HKLM_SETTINGS_JSON", ""))
        if inline_payload:
            return inline_payload, self._root_dir / "env:AGORA_CLAUDE_POLICY_HKLM_SETTINGS_JSON", "env:AGORA_CLAUDE_POLICY_HKLM_SETTINGS_JSON"
        if self._policy_hklm_settings_path is not None:
            payload = self._read_json(self._policy_hklm_settings_path)
            if payload:
                return payload, self._policy_hklm_settings_path, "env:AGORA_CLAUDE_POLICY_HKLM_SETTINGS_PATH"
        payload = self._read_windows_registry_policy("HKLM")
        if payload:
            return payload, self._root_dir / "registry:HKLM\\SOFTWARE\\Policies\\ClaudeCode\\Settings", "Registry: HKLM\\SOFTWARE\\Policies\\ClaudeCode\\Settings"
        return {}, None, ""

    def _load_hkcu_policy_settings(self) -> tuple[dict[str, Any], Path | None, str]:
        inline_payload = self._parse_inline_settings_json(os.getenv("AGORA_CLAUDE_POLICY_HKCU_SETTINGS_JSON", ""))
        if inline_payload:
            return inline_payload, self._root_dir / "env:AGORA_CLAUDE_POLICY_HKCU_SETTINGS_JSON", "env:AGORA_CLAUDE_POLICY_HKCU_SETTINGS_JSON"
        if self._policy_hkcu_settings_path is not None:
            payload = self._read_json(self._policy_hkcu_settings_path)
            if payload:
                return payload, self._policy_hkcu_settings_path, "env:AGORA_CLAUDE_POLICY_HKCU_SETTINGS_PATH"
        payload = self._read_windows_registry_policy("HKCU")
        if payload:
            return payload, self._root_dir / "registry:HKCU\\SOFTWARE\\Policies\\ClaudeCode\\Settings", "Registry: HKCU\\SOFTWARE\\Policies\\ClaudeCode\\Settings"
        return {}, None, ""

    def _macos_mdm_plist_candidates(self) -> list[tuple[Path, str]]:
        if self._mdm_plist_override_paths:
            return [(path, f"override plist: {path.name}") for path in self._mdm_plist_override_paths]
        username = str(os.getenv("USER") or Path.home().name or "").strip()
        candidates: list[tuple[Path, str]] = []
        if username:
            candidates.append(
                (
                    Path("/Library/Managed Preferences") / username / f"{_CLAUDE_MACOS_PREFERENCE_DOMAIN}.plist",
                    "per-user managed preferences",
                )
            )
        candidates.append(
            (
                Path("/Library/Managed Preferences") / f"{_CLAUDE_MACOS_PREFERENCE_DOMAIN}.plist",
                "device-level managed preferences",
            )
        )
        return [(path.resolve(), label) for path, label in candidates]

    @staticmethod
    def _read_plist(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _read_windows_registry_policy(hive: str) -> dict[str, Any]:
        if os.name != "nt":
            return {}
        try:
            import winreg
        except Exception:
            return {}
        hive_name = str(hive or "").strip().upper()
        if hive_name == "HKLM":
            registry_hive = winreg.HKEY_LOCAL_MACHINE
            key_path = _CLAUDE_WINDOWS_REGISTRY_KEY_PATH_HKLM
        elif hive_name == "HKCU":
            registry_hive = winreg.HKEY_CURRENT_USER
            key_path = _CLAUDE_WINDOWS_REGISTRY_KEY_PATH_HKCU
        else:
            return {}
        try:
            with winreg.OpenKey(registry_hive, key_path) as key:
                raw_value, _ = winreg.QueryValueEx(key, _CLAUDE_WINDOWS_REGISTRY_VALUE_NAME)
        except Exception:
            return {}
        if isinstance(raw_value, bytes):
            try:
                raw_text = raw_value.decode("utf-8")
            except Exception:
                return {}
        else:
            raw_text = str(raw_value or "")
        try:
            payload = json.loads(raw_text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _permission_rule_matches(self, *, rule: ImportedClaudePermissionRule, action: Any) -> bool:
        action_name = str(getattr(action, "action", "") or "").strip()
        payload = dict(getattr(action, "payload", {}) or {})
        tool_name = str(rule.tool_name or "").strip()
        normalized_tool_name = tool_name.lower()
        if not action_name or not tool_name:
            return False
        if tool_name.startswith("mcp__"):
            if action_name.startswith("mcp__"):
                if tool_name.endswith("__*"):
                    return action_name.startswith(tool_name[:-1])
                if "__" not in tool_name[5:]:
                    return action_name.startswith(tool_name + "__")
                return action_name == tool_name
            if action_name == "read_mcp_resource":
                server_id = str(payload.get("server_id") or "").strip()
                if not server_id:
                    return False
                if tool_name == f"mcp__{server_id}" or tool_name == f"mcp__{server_id}__*":
                    return True
            return False
        if normalized_tool_name == "bash":
            if action_name not in {"run_terminal", "run_targeted_test", "verify_git_state", "run_sandbox_verification"}:
                return False
            if not rule.rule_content:
                return True
            return _match_shell_permission_rule(rule.rule_content, self._command_text_from_payload(payload))
        if normalized_tool_name == "webfetch":
            if action_name not in {"web_fetch", "web_search", "browser_interact"}:
                return False
            if not rule.rule_content:
                return True
            rule_content = str(rule.rule_content or "").strip()
            if rule_content.startswith("domain:"):
                domain = self._domain_from_payload(action_name=action_name, payload=payload)
                domain_pattern = rule_content.split(":", 1)[1].strip()
                return bool(domain and _match_shell_permission_rule(domain_pattern, domain))
            return False
        read_actions = {"read_file", "read_session_file", "list_dir", "propose_patch", "read_mcp_resource"}
        edit_actions = {"apply_patch"}
        write_actions = {"apply_patch", "write_decision_draft"}
        allowed_actions: set[str] = set()
        if normalized_tool_name == "read":
            allowed_actions = read_actions
        elif normalized_tool_name == "edit":
            allowed_actions = edit_actions
        elif normalized_tool_name == "write":
            allowed_actions = write_actions
        if not allowed_actions or action_name not in allowed_actions:
            return False
        if not rule.rule_content:
            return True
        workspace_root = self._workspace_root_from_payload(payload)
        candidate_paths = _path_candidates_for_rule_match(payload=payload, workspace_root=workspace_root, fallback_root=self._root_dir)
        return _match_path_glob(rule.rule_content, candidate_paths)

    @staticmethod
    def _command_text_from_payload(payload: dict[str, Any]) -> str:
        command_value = payload.get("command")
        if command_value is None:
            command_value = payload.get("cmd")
        commands_value = payload.get("commands")
        if isinstance(command_value, list):
            return " ".join(str(part) for part in command_value if str(part).strip()).strip()
        if isinstance(commands_value, list):
            return "\n".join(str(part) for part in commands_value if str(part).strip()).strip()
        return str(command_value or payload.get("command_text") or "").strip()

    @staticmethod
    def _domain_from_payload(*, action_name: str, payload: dict[str, Any]) -> str:
        if action_name == "web_fetch":
            raw = str(payload.get("domain") or "").strip()
            if raw:
                return raw.lower()
            url = str(payload.get("url") or "").strip()
            match = re.match(r"^[A-Za-z]+://([^/]+)", url)
            return str(match.group(1) if match else "").strip().lower()
        if action_name == "browser_interact":
            for key in ("url", "page_url", "target_url"):
                url = str(payload.get(key) or "").strip()
                if not url:
                    continue
                match = re.match(r"^[A-Za-z]+://([^/]+)", url)
                domain = str(match.group(1) if match else "").strip().lower()
                if domain:
                    return domain
            return ""
        return str(payload.get("search_provider_domain") or "duckduckgo.com").strip().lower()

    def _workspace_root_from_payload(self, payload: dict[str, Any]) -> Path | None:
        raw = str(payload.get("sandbox_workspace_root") or "").strip()
        if not raw:
            return None
        try:
            return Path(raw).expanduser().resolve()
        except Exception:
            return None
