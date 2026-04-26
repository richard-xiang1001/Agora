from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable, Any
import tomllib

import yaml


SKILL_BODY_MAX_CHARS = 6000
SKILL_TOTAL_CONTEXT_MAX_CHARS = 12000


@dataclass(frozen=True)
class SkillEntry:
    skill_id: str
    name: str
    description: str
    skill_path: Path
    source: str
    is_system: bool = False

    def model_dump(self) -> dict[str, str | bool]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "skill_path": str(self.skill_path),
            "source": self.source,
            "is_system": self.is_system,
        }


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    name: str
    description: str
    skill_path: Path
    source: str
    is_system: bool
    entry_path: Path
    references_dir: Path | None
    scripts_dir: Path | None
    script_paths: tuple[str, ...]
    preferred_entry_script: str | None
    required_bins: tuple[str, ...]
    required_python_packages: tuple[str, ...]
    needs_network: bool
    workspace_access: str
    approval_class: str
    execution_mode: str
    trust_level: str
    auto_trust_candidate: bool
    trust_summary: str
    trust_reasons: tuple[str, ...]
    bootstrap_commands: tuple[str, ...]
    entry_command: tuple[str, ...] | None

    def capability_summary(self) -> dict[str, Any]:
        can_write = self.workspace_access in {"read_write", "host_escape"}
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "source": self.source,
            "is_system": self.is_system,
            "execution_mode": self.execution_mode,
            "approval_class": self.approval_class,
            "workspace_access": self.workspace_access,
            "trust_level": self.trust_level,
            "auto_trust_candidate": self.auto_trust_candidate,
            "needs_network": self.needs_network,
            "can_write_workspace": can_write,
            "is_read_only_exec": self.execution_mode == "read_only_exec",
            "is_guidance_only": self.execution_mode == "guidance_only",
            "has_entry_script": bool(self.preferred_entry_script),
            "preferred_entry_script": self.preferred_entry_script,
            "required_bins": list(self.required_bins),
        }

    def dependency_summary(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "source": self.source,
            "scripts_dir": str(self.scripts_dir) if self.scripts_dir else None,
            "references_dir": str(self.references_dir) if self.references_dir else None,
            "script_paths": list(self.script_paths),
            "preferred_entry_script": self.preferred_entry_script,
            "required_bins": list(self.required_bins),
            "required_python_packages": list(self.required_python_packages),
            "bootstrap_commands": list(self.bootstrap_commands),
            "entry_command": list(self.entry_command) if self.entry_command else None,
            "needs_network": self.needs_network,
            "workspace_access": self.workspace_access,
        }

    def model_dump(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "skill_path": str(self.skill_path),
            "source": self.source,
            "is_system": self.is_system,
            "entry_path": str(self.entry_path),
            "references_dir": str(self.references_dir) if self.references_dir else None,
            "scripts_dir": str(self.scripts_dir) if self.scripts_dir else None,
            "script_paths": list(self.script_paths),
            "preferred_entry_script": self.preferred_entry_script,
            "required_bins": list(self.required_bins),
            "required_python_packages": list(self.required_python_packages),
            "needs_network": self.needs_network,
            "workspace_access": self.workspace_access,
            "approval_class": self.approval_class,
            "execution_mode": self.execution_mode,
            "trust_level": self.trust_level,
            "auto_trust_candidate": self.auto_trust_candidate,
            "trust_summary": self.trust_summary,
            "trust_reasons": list(self.trust_reasons),
            "bootstrap_commands": list(self.bootstrap_commands),
            "entry_command": list(self.entry_command) if self.entry_command else None,
            "capability_summary": self.capability_summary(),
            "dependency_summary": self.dependency_summary(),
        }


@dataclass(frozen=True)
class ResolvedSkillExecution:
    skill_id: str
    manifest: SkillManifest
    selected_script: str | None
    command: tuple[str, ...] | None
    references: tuple[str, ...]
    host_escape_required: bool
    network_required: bool
    workspace_access: str
    approval_class: str
    execution_mode: str
    trust_level: str
    auto_trust_candidate: bool
    trust_summary: str
    trust_reasons: tuple[str, ...]
    bootstrap_commands: tuple[str, ...]
    entry_command: tuple[str, ...] | None

    def capability_summary(self) -> dict[str, Any]:
        manifest_capability = self.manifest.capability_summary()
        return {
            **manifest_capability,
            "selected_script": self.selected_script,
            "command": list(self.command) if self.command else None,
            "references_count": len(self.references),
            "references": list(self.references),
            "host_escape_required": self.host_escape_required,
            "bootstrap_commands_count": len(self.bootstrap_commands),
            "selected_script_matches_manifest": self.selected_script == self.manifest.preferred_entry_script,
        }

    def dependency_summary(self) -> dict[str, Any]:
        manifest_dependency = self.manifest.dependency_summary()
        return {
            **manifest_dependency,
            "selected_script": self.selected_script,
            "command": list(self.command) if self.command else None,
            "references": list(self.references),
            "references_count": len(self.references),
            "host_escape_required": self.host_escape_required,
        }

    def model_dump(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "manifest": self.manifest.model_dump(),
            "selected_script": self.selected_script,
            "command": list(self.command) if self.command else None,
            "references": list(self.references),
            "host_escape_required": self.host_escape_required,
            "network_required": self.network_required,
            "workspace_access": self.workspace_access,
            "approval_class": self.approval_class,
            "execution_mode": self.execution_mode,
            "trust_level": self.trust_level,
            "auto_trust_candidate": self.auto_trust_candidate,
            "trust_summary": self.trust_summary,
            "trust_reasons": list(self.trust_reasons),
            "bootstrap_commands": list(self.bootstrap_commands),
            "entry_command": list(self.entry_command) if self.entry_command else None,
            "capability_summary": self.capability_summary(),
            "dependency_summary": self.dependency_summary(),
        }


def _normalize_skill_id(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower())
    normalized = re.sub(r"-{2,}", "-", lowered).strip("-")
    return normalized or "unknown-skill"


def normalize_workspace_access(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"ro", "read_only", "readonly"}:
        return "read_only"
    if normalized in {"rw", "read_write", "readwrite"}:
        return "read_write"
    if normalized == "host_escape":
        return "host_escape"
    return "none"


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    source = str(text or "")
    if not source.startswith("---\n"):
        return {}, source.strip()
    end = source.find("\n---\n", 4)
    if end == -1:
        return {}, source.strip()
    frontmatter_raw = source[4:end]
    body = source[end + 5 :].strip()
    try:
        payload = yaml.safe_load(frontmatter_raw) or {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload, body


class SkillRegistry:
    def __init__(self, entries: Iterable[SkillEntry], *, disabled_skill_ids: Iterable[str] | None = None) -> None:
        ordered = sorted(entries, key=lambda item: (item.is_system, item.skill_id))
        self._entries = list(ordered)
        self._by_id = {item.skill_id: item for item in self._entries}
        self._manifest_cache: dict[str, SkillManifest] = {}
        self._disabled_ids = {_normalize_skill_id(item) for item in (disabled_skill_ids or []) if str(item or "").strip()}

    @classmethod
    def discover(
        cls,
        *,
        repo_root: Path,
        root_dir: Path,
        home_dir: Path | None = None,
        disabled_skill_ids: Iterable[str] | None = None,
    ) -> SkillRegistry:
        home = home_dir or Path.home()
        search_roots = [
            ("workspace", root_dir / ".agora" / "skills"),
            ("user", home / ".agora" / "skills"),
            ("codex_user", home / ".codex" / "skills"),
            ("bundled", repo_root / "skills"),
        ]
        priority = {"bundled": 0, "codex_user": 1, "user": 2, "workspace": 3}
        chosen: dict[str, SkillEntry] = {}
        chosen_priority: dict[str, int] = {}
        for source, root in search_roots:
            if not root.exists():
                continue
            for skill_path in root.rglob("SKILL.md"):
                try:
                    rel_parts = skill_path.relative_to(root).parts
                except Exception:
                    rel_parts = ()
                if len(rel_parts) > 3:
                    continue
                raw = skill_path.read_text(encoding="utf-8")
                frontmatter, _ = _split_frontmatter(raw)
                raw_name = str(frontmatter.get("name") or skill_path.parent.name)
                description = str(frontmatter.get("description") or "").strip()
                skill_id = _normalize_skill_id(raw_name)
                entry = SkillEntry(
                    skill_id=skill_id,
                    name=raw_name.strip() or skill_id,
                    description=description,
                    skill_path=skill_path.resolve(),
                    source=source,
                    is_system=".system" in skill_path.parts,
                )
                if skill_id not in chosen or priority[source] >= chosen_priority[skill_id]:
                    chosen[skill_id] = entry
                    chosen_priority[skill_id] = priority[source]
        return cls(chosen.values(), disabled_skill_ids=disabled_skill_ids)

    def set_disabled_skills(self, skill_ids: Iterable[str]) -> None:
        self._disabled_ids = {_normalize_skill_id(item) for item in skill_ids if str(item or "").strip()}

    def disabled_skill_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._disabled_ids))

    def is_enabled(self, skill_id: str) -> bool:
        return _normalize_skill_id(skill_id) not in self._disabled_ids

    def list_skills(self, *, include_disabled: bool = False) -> list[SkillEntry]:
        if include_disabled:
            return list(self._entries)
        return [item for item in self._entries if self.is_enabled(item.skill_id)]

    def get(self, skill_id: str, *, include_disabled: bool = False) -> SkillEntry | None:
        normalized = _normalize_skill_id(skill_id)
        entry = self._by_id.get(normalized)
        if entry is None:
            return None
        if not include_disabled and normalized in self._disabled_ids:
            return None
        return entry

    def build_prompt_summary(self, *, max_skills: int = 12) -> str:
        visible_entries = self.list_skills()
        if not visible_entries:
            return "No local skills are currently installed."
        visible = visible_entries[:max_skills]
        lines = [
            "Discovered local skills are listed below. They are not preloaded by default.",
            "If the user explicitly mentions a skill name or writes $skill-id, load that skill's SKILL.md for this turn before following it.",
        ]
        for entry in visible:
            suffix = " [system]" if entry.is_system else ""
            description = entry.description or "No description provided."
            lines.append(f"- ${entry.skill_id}{suffix}: {description} (source: {entry.source})")
        remaining = len(visible_entries) - len(visible)
        if remaining > 0:
            lines.append(f"- ... plus {remaining} more installed skills not shown here.")
        return "\n".join(lines)

    @staticmethod
    def _load_skills_whitelist(*, root_dir: Path | None = None, repo_root: Path | None = None) -> dict[str, Any]:
        candidate_paths: list[Path] = []
        if root_dir is not None:
            candidate_paths.append(root_dir.resolve() / "config" / "skills_whitelist.json")
        if repo_root is not None:
            candidate_paths.append(repo_root.resolve() / "config" / "skills_whitelist.json")
        seen: set[str] = set()
        for path in candidate_paths:
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                return {
                    "present": True,
                    "source": str(path),
                    "entries": [],
                    "parse_error": exc.__class__.__name__,
                }
            entries = payload.get("entries")
            return {
                "present": True,
                "source": str(path),
                "entries": list(entries) if isinstance(entries, list) else [],
                "parse_error": "",
            }
        return {
            "present": False,
            "source": "",
            "entries": [],
            "parse_error": "",
        }

    def _runtime_skill_overlay_row(
        self,
        *,
        skill_id: str,
        entry: SkillEntry | None,
        manifest: SkillManifest | None,
        exposure_reason: str,
        whitelisted: bool,
        whitelist_scope: str,
        scope_matches: bool,
        loaded_for_turn: bool,
    ) -> dict[str, Any]:
        description = str(entry.description if entry is not None else "").strip()
        capability = manifest.capability_summary() if manifest is not None else {}
        return {
            "skill_id": skill_id,
            "name": str(entry.name if entry is not None else skill_id),
            "description": description,
            "source": str(entry.source if entry is not None else ""),
            "exposure_reason": exposure_reason,
            "whitelisted": whitelisted,
            "whitelist_scope": whitelist_scope,
            "scope_matches": scope_matches,
            "loaded_for_turn": loaded_for_turn,
            "execution_mode": str(capability.get("execution_mode") or ""),
            "workspace_access": str(capability.get("workspace_access") or ""),
            "trust_level": str(capability.get("trust_level") or ""),
            "approval_class": str(capability.get("approval_class") or ""),
            "needs_network": bool(capability.get("needs_network")),
            "is_system": bool(capability.get("is_system")),
        }

    def build_runtime_skill_surface(
        self,
        *,
        permissions_scope: str | None,
        root_dir: Path | None = None,
        repo_root: Path | None = None,
        loaded_skills: list[dict[str, Any]] | None = None,
        max_skills: int = 8,
        include_disabled: bool = False,
    ) -> dict[str, Any]:
        entries = self.list_skills(include_disabled=include_disabled)
        discovered_by_id = {item.skill_id: item for item in entries}
        whitelist_payload = self._load_skills_whitelist(root_dir=root_dir, repo_root=repo_root)
        whitelist_rows = [item for item in list(whitelist_payload.get("entries") or []) if isinstance(item, dict)]
        permissions_scope_text = str(permissions_scope or "").strip()
        whitelist_index: dict[str, dict[str, Any]] = {}
        scope_match_count = 0
        whitelisted_discovered_count = 0
        for item in whitelist_rows:
            skill_id = _normalize_skill_id(str(item.get("name") or item.get("skill_id") or item.get("id") or ""))
            if not skill_id:
                continue
            whitelist_scope = str(item.get("permissions_scope") or "").strip()
            scope_matches = bool(not whitelist_scope or (permissions_scope_text and whitelist_scope == permissions_scope_text))
            discovered_entry = discovered_by_id.get(skill_id)
            if discovered_entry is not None:
                whitelisted_discovered_count += 1
                if scope_matches:
                    scope_match_count += 1
            whitelist_index[skill_id] = {
                "whitelist_scope": whitelist_scope,
                "scope_matches": scope_matches,
            }

        visible: list[dict[str, Any]] = []
        visible_ids: set[str] = set()
        loaded_ids: list[str] = []
        for item in list(loaded_skills or []):
            skill_id = _normalize_skill_id(str(item.get("skill_id") or ""))
            if not skill_id or skill_id in visible_ids:
                continue
            entry = self.get(skill_id, include_disabled=include_disabled)
            manifest = self.get_manifest(skill_id, include_disabled=include_disabled)
            whitelist_row = dict(whitelist_index.get(skill_id) or {})
            visible.append(
                self._runtime_skill_overlay_row(
                    skill_id=skill_id,
                    entry=entry,
                    manifest=manifest,
                    exposure_reason="loaded_for_turn",
                    whitelisted=bool(whitelist_row),
                    whitelist_scope=str(whitelist_row.get("whitelist_scope") or ""),
                    scope_matches=bool(whitelist_row.get("scope_matches")),
                    loaded_for_turn=True,
                )
            )
            visible_ids.add(skill_id)
            loaded_ids.append(skill_id)

        if whitelist_payload.get("present"):
            for skill_id, whitelist_row in whitelist_index.items():
                if skill_id in visible_ids or not bool(whitelist_row.get("scope_matches")):
                    continue
                entry = self.get(skill_id, include_disabled=include_disabled)
                if entry is None:
                    continue
                manifest = self.get_manifest(skill_id, include_disabled=include_disabled)
                visible.append(
                    self._runtime_skill_overlay_row(
                        skill_id=skill_id,
                        entry=entry,
                        manifest=manifest,
                        exposure_reason="whitelisted_for_scope",
                        whitelisted=True,
                        whitelist_scope=str(whitelist_row.get("whitelist_scope") or ""),
                        scope_matches=True,
                        loaded_for_turn=False,
                    )
                )
                visible_ids.add(skill_id)
        else:
            for entry in entries:
                if entry.skill_id in visible_ids:
                    continue
                manifest = self.get_manifest(entry.skill_id, include_disabled=include_disabled)
                visible.append(
                    self._runtime_skill_overlay_row(
                        skill_id=entry.skill_id,
                        entry=entry,
                        manifest=manifest,
                        exposure_reason="discovered_no_whitelist",
                        whitelisted=False,
                        whitelist_scope="",
                        scope_matches=False,
                        loaded_for_turn=False,
                    )
                )
                visible_ids.add(entry.skill_id)
                if len(visible) >= max_skills:
                    break

        truncated_visible = visible[:max_skills]
        visible_skill_ids = [str(item.get("skill_id") or "").strip() for item in truncated_visible if str(item.get("skill_id") or "").strip()]
        discovered_visible_count = len({item for item in visible_skill_ids if item in discovered_by_id})
        return {
            "policy_mode": "whitelist" if whitelist_payload.get("present") else "discovered",
            "permissions_scope": permissions_scope_text,
            "whitelist_present": bool(whitelist_payload.get("present")),
            "whitelist_source": str(whitelist_payload.get("source") or ""),
            "whitelist_parse_error": str(whitelist_payload.get("parse_error") or ""),
            "whitelist_count": len(whitelist_rows),
            "whitelisted_discovered_count": whitelisted_discovered_count,
            "scope_match_count": scope_match_count,
            "discovered_count": len(entries),
            "loaded_count": len(loaded_ids),
            "visible_count": len(truncated_visible),
            "hidden_discovered_count": max(0, len(entries) - discovered_visible_count),
            "skills": visible_skill_ids,
            "details": truncated_visible,
        }

    def build_runtime_capability_summary(self, *, max_skills: int = 12, include_disabled: bool = False) -> dict[str, Any]:
        entries = self.list_skills(include_disabled=include_disabled)
        visible = entries[:max_skills]
        return {
            "skill_count": len(entries),
            "visible_count": len(visible),
            "max_skills": max_skills,
            "include_disabled": include_disabled,
            "skills": [item.skill_id for item in visible],
            "details": [self.get_manifest(item.skill_id, include_disabled=include_disabled).capability_summary() for item in visible if self.get_manifest(item.skill_id, include_disabled=include_disabled) is not None],
        }

    def build_dependency_summary(self, *, max_skills: int = 12, include_disabled: bool = False) -> dict[str, Any]:
        entries = self.list_skills(include_disabled=include_disabled)
        visible = entries[:max_skills]
        manifests = [self.get_manifest(item.skill_id, include_disabled=include_disabled) for item in visible]
        manifests = [item for item in manifests if item is not None]
        return {
            "skill_count": len(entries),
            "visible_count": len(visible),
            "max_skills": max_skills,
            "include_disabled": include_disabled,
            "skills": [item.skill_id for item in visible],
            "details": [item.dependency_summary() for item in manifests],
        }

    @staticmethod
    def _scripts_dir(entry: SkillEntry) -> Path | None:
        path = entry.skill_path.parent / "scripts"
        return path.resolve() if path.exists() and path.is_dir() else None

    @staticmethod
    def _references_dir(entry: SkillEntry) -> Path | None:
        path = entry.skill_path.parent / "references"
        return path.resolve() if path.exists() and path.is_dir() else None

    @staticmethod
    def _script_paths(scripts_dir: Path | None) -> tuple[str, ...]:
        if scripts_dir is None:
            return ()
        items = []
        for path in sorted(scripts_dir.rglob("*")):
            if path.is_file():
                items.append(str(path.relative_to(scripts_dir)))
        return tuple(items)

    @staticmethod
    def _hinted_script_paths(body: str) -> list[str]:
        hints: list[str] = []
        for match in re.finditer(r"`(scripts/[^`]+)`", str(body or "")):
            raw = str(match.group(1) or "").strip()
            if raw.startswith("scripts/"):
                hints.append(raw.replace("scripts/", "", 1))
        return hints

    @staticmethod
    def _preferred_entry_script(*, body: str, script_paths: tuple[str, ...]) -> str | None:
        hinted = SkillRegistry._hinted_script_paths(body)
        for candidate in hinted:
            if candidate in script_paths:
                return candidate
        if len(script_paths) == 1:
            return script_paths[0]
        for suffix in ("main.py", "run.py", "index.py", "main.sh", "run.sh"):
            for candidate in script_paths:
                if candidate.endswith(suffix):
                    return candidate
        for candidate in script_paths:
            if candidate.endswith((".py", ".sh", ".js", ".mjs")):
                return candidate
        return script_paths[0] if script_paths else None

    @staticmethod
    def _required_bins(body: str) -> tuple[str, ...]:
        bins: list[str] = []
        in_fence = False
        for raw in str(body or "").splitlines():
            line = raw.strip()
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence or not line:
                continue
            token = line.split()[0]
            token = token.replace("$", "").strip()
            if token in {"python", "python3", "uv", "node", "npm", "pnpm", "yarn", "bash", "sh", "brew", "docker", "gh", "git", "soffice", "pdftoppm"}:
                bins.append(token)
        seen = []
        for item in bins:
            if item not in seen:
                seen.append(item)
        return tuple(seen)

    @staticmethod
    def _needs_network(body: str) -> bool:
        lowered = str(body or "").lower()
        return any(
            token in lowered
            for token in (
                "http://",
                "https://",
                "github api",
                "internet",
                "network",
                "download",
                "remote",
                "fetch",
            )
        )

    @staticmethod
    def _workspace_access(body: str, script_paths: tuple[str, ...]) -> str:
        lowered = str(body or "").lower()
        if script_paths and any(
            token in lowered
            for token in (
                "write ",
                "writes ",
                "create ",
                "creates ",
                "edit ",
                "editing ",
                "install ",
                "output/",
                "output_dir",
                "tmp/",
                "tmp ",
                "final artifact",
            )
        ):
            return "read_write"
        return "read_only"

    @staticmethod
    def _approval_class(*, preferred_entry_script: str | None, needs_network: bool, workspace_access: str) -> str:
        if needs_network:
            return "networked"
        if preferred_entry_script and workspace_access == "read_write":
            return "exec_write"
        if preferred_entry_script:
            return "exec_read"
        return "read_only"

    @staticmethod
    def _execution_mode(*, preferred_entry_script: str | None, needs_network: bool, workspace_access: str) -> str:
        if needs_network:
            return "networked"
        if workspace_access == "host_escape":
            return "host_escape"
        if not preferred_entry_script:
            return "guidance_only"
        if workspace_access == "read_write":
            return "write_exec"
        return "read_only_exec"

    @staticmethod
    def _trust_profile(
        *,
        source: str,
        is_system: bool,
        execution_mode: str,
        approval_class: str,
        workspace_access: str,
        needs_network: bool,
    ) -> tuple[str, bool, str, tuple[str, ...]]:
        reasons: list[str] = []
        if execution_mode == "guidance_only":
            reasons.append("guidance only, no executable entry script")
        elif execution_mode == "read_only_exec":
            reasons.append("read-only execution path")
        elif execution_mode == "write_exec":
            reasons.append("writes to the workspace")
        elif execution_mode == "networked":
            reasons.append("requires network access")
        elif execution_mode == "host_escape":
            reasons.append("requires host-level access")
        if approval_class:
            reasons.append(f"approval class {approval_class}")
        if workspace_access:
            reasons.append(f"workspace access {workspace_access}")
        if needs_network and "requires network access" not in reasons:
            reasons.append("requires network access")
        if is_system:
            reasons.append("system-provided skill")
        elif source:
            reasons.append(f"skill source {source}")
        auto_trust_candidate = (
            execution_mode in {"guidance_only", "read_only_exec"}
            and not needs_network
            and workspace_access in {"none", "read_only"}
            and approval_class in {"read_only", "exec_read"}
        )
        if execution_mode in {"write_exec", "networked", "host_escape"}:
            trust_level = "guarded"
        elif auto_trust_candidate and is_system:
            trust_level = "high"
        elif auto_trust_candidate:
            trust_level = "medium"
        else:
            trust_level = "guarded"
        summary = {
            "guidance_only": "Guidance-only skill with no executable entry point.",
            "read_only_exec": "Read-only executable skill.",
            "write_exec": "Executable skill that can write to the workspace.",
            "networked": "Executable skill that needs network access.",
            "host_escape": "Skill that requires host-level access.",
        }.get(execution_mode, "Skill trust posture is guarded.")
        if auto_trust_candidate:
            summary = f"{summary} Candidate for auto-trust because it stays read-only and offline."
        else:
            summary = f"{summary} Not an auto-trust candidate."
        return trust_level, auto_trust_candidate, summary, tuple(reasons)

    @staticmethod
    def _requirements_txt(entry: SkillEntry) -> Path | None:
        path = entry.skill_path.parent / "requirements.txt"
        return path.resolve() if path.exists() and path.is_file() else None

    @staticmethod
    def _pyproject_toml(entry: SkillEntry) -> Path | None:
        path = entry.skill_path.parent / "pyproject.toml"
        return path.resolve() if path.exists() and path.is_file() else None

    @staticmethod
    def _package_json(entry: SkillEntry) -> Path | None:
        path = entry.skill_path.parent / "package.json"
        return path.resolve() if path.exists() and path.is_file() else None

    @staticmethod
    def _required_python_packages(entry: SkillEntry) -> tuple[str, ...]:
        packages: list[str] = []
        requirements_txt = SkillRegistry._requirements_txt(entry)
        if requirements_txt is not None:
            for raw in requirements_txt.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                packages.append(line)
        pyproject = SkillRegistry._pyproject_toml(entry)
        if pyproject is not None:
            try:
                payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            project = payload.get("project") if isinstance(payload, dict) else {}
            dependencies = project.get("dependencies") if isinstance(project, dict) else []
            if isinstance(dependencies, list):
                for item in dependencies:
                    name = re.split(r"[<>=!~\[]", str(item or "").strip(), maxsplit=1)[0].strip()
                    if name:
                        packages.append(name)
        unique: list[str] = []
        for item in packages:
            if item not in unique:
                unique.append(item)
        return tuple(unique)

    @staticmethod
    def _entry_command_for_script(selected_script: str | None) -> tuple[str, ...] | None:
        if not selected_script:
            return None
        script_path = Path(selected_script)
        suffix = script_path.suffix.lower()
        target = f"/agora/skill/scripts/{selected_script}"
        if suffix == ".py":
            return ("python3", target)
        if suffix in {".sh", ".bash"}:
            return ("sh", target)
        if suffix in {".js", ".mjs"}:
            return ("node", target)
        return (target,)

    @staticmethod
    def _bootstrap_commands(entry: SkillEntry, *, selected_script: str | None, required_python_packages: tuple[str, ...]) -> tuple[str, ...]:
        commands: list[str] = []
        if SkillRegistry._requirements_txt(entry) is not None:
            commands.append("python3 -m pip install -r /agora/skill/requirements.txt")
        elif SkillRegistry._pyproject_toml(entry) is not None and required_python_packages:
            commands.append("python3 -m pip install -e /agora/skill")
        if SkillRegistry._package_json(entry) is not None:
            commands.append("npm install --no-audit --no-fund")
        if selected_script and selected_script.endswith((".js", ".mjs")) and SkillRegistry._package_json(entry) is None:
            commands.append("npm install --no-audit --no-fund")
        unique: list[str] = []
        for item in commands:
            if item not in unique:
                unique.append(item)
        return tuple(unique)

    def get_manifest(self, skill_id: str, *, include_disabled: bool = False) -> SkillManifest | None:
        normalized = _normalize_skill_id(skill_id)
        if not include_disabled and normalized in self._disabled_ids:
            return None
        if normalized in self._manifest_cache:
            return self._manifest_cache[normalized]
        entry = self.get(normalized, include_disabled=include_disabled)
        if entry is None:
            return None
        payload = self.read_skill(normalized, include_disabled=include_disabled)
        body = str(payload.get("body") or "")
        scripts_dir = self._scripts_dir(entry)
        references_dir = self._references_dir(entry)
        script_paths = self._script_paths(scripts_dir)
        preferred_entry_script = self._preferred_entry_script(body=body, script_paths=script_paths)
        required_bins = self._required_bins(body)
        required_python_packages = self._required_python_packages(entry)
        needs_network = self._needs_network(body)
        workspace_access = self._workspace_access(body, script_paths)
        frontmatter_workspace_access = str(payload.get("frontmatter", {}).get("workspace_access") or "").strip().lower()
        if frontmatter_workspace_access in {"ro", "rw", "none", "read_only", "read_write", "host_escape"}:
            workspace_access = normalize_workspace_access(frontmatter_workspace_access)
        approval_class = self._approval_class(
            preferred_entry_script=preferred_entry_script,
            needs_network=needs_network,
            workspace_access=workspace_access,
        )
        execution_mode = self._execution_mode(
            preferred_entry_script=preferred_entry_script,
            needs_network=needs_network,
            workspace_access=workspace_access,
        )
        trust_level, auto_trust_candidate, trust_summary, trust_reasons = self._trust_profile(
            source=entry.source,
            is_system=entry.is_system,
            execution_mode=execution_mode,
            approval_class=approval_class,
            workspace_access=workspace_access,
            needs_network=needs_network,
        )
        entry_command = self._entry_command_for_script(preferred_entry_script)
        bootstrap_commands = self._bootstrap_commands(
            entry,
            selected_script=preferred_entry_script,
            required_python_packages=required_python_packages,
        )
        manifest = SkillManifest(
            skill_id=entry.skill_id,
            name=entry.name,
            description=entry.description,
            skill_path=entry.skill_path,
            source=entry.source,
            is_system=entry.is_system,
            entry_path=entry.skill_path.parent.resolve(),
            references_dir=references_dir,
            scripts_dir=scripts_dir,
            script_paths=script_paths,
            preferred_entry_script=preferred_entry_script,
            required_bins=required_bins,
            required_python_packages=required_python_packages,
            needs_network=needs_network,
            workspace_access=workspace_access,
            approval_class=approval_class,
            execution_mode=execution_mode,
            trust_level=trust_level,
            auto_trust_candidate=auto_trust_candidate,
            trust_summary=trust_summary,
            trust_reasons=trust_reasons,
            bootstrap_commands=bootstrap_commands,
            entry_command=entry_command,
        )
        self._manifest_cache[normalized] = manifest
        return manifest

    def resolve_execution(self, skill_id: str, *, requested_script: str | None = None) -> ResolvedSkillExecution:
        manifest = self.get_manifest(skill_id)
        if manifest is None:
            if not self.is_enabled(skill_id) and self.get(skill_id, include_disabled=True) is not None:
                raise PermissionError(f"disabled skill: {skill_id}")
            raise FileNotFoundError(f"unknown skill: {skill_id}")
        selected_script = str(requested_script or manifest.preferred_entry_script or "").strip() or None
        if selected_script and selected_script not in manifest.script_paths:
            raise FileNotFoundError(f"unknown skill script: {selected_script}")
        command = self._entry_command_for_script(selected_script)
        references: tuple[str, ...] = ()
        if manifest.references_dir is not None:
            refs = []
            for path in sorted(manifest.references_dir.rglob("*")):
                if path.is_file():
                    refs.append(str(path.relative_to(manifest.entry_path)))
            references = tuple(refs)
        host_escape_required = bool(manifest.needs_network)
        return ResolvedSkillExecution(
            skill_id=manifest.skill_id,
            manifest=manifest,
            selected_script=selected_script,
            command=command,
            references=references,
            host_escape_required=host_escape_required,
            network_required=manifest.needs_network,
            workspace_access=manifest.workspace_access,
            approval_class=manifest.approval_class,
            execution_mode=manifest.execution_mode,
            trust_level=manifest.trust_level,
            auto_trust_candidate=manifest.auto_trust_candidate,
            trust_summary=manifest.trust_summary,
            trust_reasons=manifest.trust_reasons,
            bootstrap_commands=manifest.bootstrap_commands,
            entry_command=command,
        )

    def _matches_in_text(self, *, entry: SkillEntry, lowered_text: str) -> bool:
        explicit_pattern = rf"\${re.escape(entry.skill_id)}(?![A-Za-z0-9._-])"
        if re.search(explicit_pattern, lowered_text):
            return True
        aliases = {entry.skill_id, str(entry.name or "").strip().lower()}
        for alias in aliases:
            if not alias or len(alias) < 4:
                continue
            pattern = rf"(?<![A-Za-z0-9._-]){re.escape(alias)}(?![A-Za-z0-9._-])"
            if re.search(pattern, lowered_text):
                return True
        return False

    def match_requested_skills(self, message: str, *, max_skills: int = 2) -> list[SkillEntry]:
        lowered = str(message or "").strip().lower()
        if not lowered:
            return []
        matches: list[SkillEntry] = []
        for entry in self.list_skills():
            if self._matches_in_text(entry=entry, lowered_text=lowered):
                matches.append(entry)
            if len(matches) >= max_skills:
                break
        return matches

    @staticmethod
    def _truncate(text: str, limit: int) -> tuple[str, bool]:
        normalized = str(text or "").strip()
        if len(normalized) <= limit:
            return normalized, False
        suffix = "\n[Truncated skill body.]"
        keep = max(0, limit - len(suffix))
        return normalized[:keep].rstrip() + suffix, True

    def read_skill(self, skill_id: str, *, include_disabled: bool = False) -> dict[str, object]:
        entry = self.get(skill_id, include_disabled=include_disabled)
        if entry is None:
            raise FileNotFoundError(f"unknown skill: {skill_id}")
        raw = entry.skill_path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(raw)
        return {
            "entry": entry,
            "frontmatter": frontmatter,
            "body": body,
        }

    def read_reference(self, skill_id: str, relative_path: str) -> str:
        entry = self.get(skill_id)
        if entry is None:
            raise FileNotFoundError(f"unknown skill: {skill_id}")
        rel = Path(str(relative_path or "").strip())
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise PermissionError("invalid reference path")
        target = (entry.skill_path.parent / rel).resolve()
        skill_root = entry.skill_path.parent.resolve()
        if skill_root not in target.parents and target != skill_root:
            raise PermissionError("reference path escapes skill root")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"missing reference: {relative_path}")
        return target.read_text(encoding="utf-8")

    def build_turn_skill_context(self, message: str) -> tuple[str | None, list[dict[str, object]]]:
        entries = self.match_requested_skills(message)
        if not entries:
            return None, []
        remaining = SKILL_TOTAL_CONTEXT_MAX_CHARS
        blocks: list[str] = [
            "The following skill instructions were explicitly requested or clearly named by the user.",
            "Follow them for this turn when they are relevant. Treat them as workflow guidance, not proof that a tool already ran.",
        ]
        loaded: list[dict[str, object]] = []
        for entry in entries:
            payload = self.read_skill(entry.skill_id)
            body = str(payload.get("body") or "").strip()
            if remaining <= 0:
                break
            clipped, truncated = self._truncate(body, min(SKILL_BODY_MAX_CHARS, remaining))
            if not clipped:
                continue
            blocks.extend(
                [
                    "",
                    f"## Skill: {entry.name}",
                    f"Skill ID: {entry.skill_id}",
                    f"Source: {entry.source}",
                    clipped,
                ]
            )
            remaining = max(0, remaining - len(clipped))
            loaded.append(
                {
                    "skill_id": entry.skill_id,
                    "name": entry.name,
                    "source": entry.source,
                    "skill_path": str(entry.skill_path),
                    "truncated": truncated,
                    "manifest": self.get_manifest(entry.skill_id).model_dump() if self.get_manifest(entry.skill_id) is not None else None,
                }
            )
        if not loaded:
            return None, []
        return "\n".join(blocks).strip(), loaded
