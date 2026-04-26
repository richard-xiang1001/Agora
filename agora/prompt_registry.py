from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agora.prompt_types import PromptAsset, PromptCatalogEntry, PromptProfile


class PromptRegistryError(RuntimeError):
    pass


class PromptTypeMismatchError(PromptRegistryError):
    pass


@dataclass
class _CachedPrompt:
    asset: PromptAsset


class PromptRegistry:
    def __init__(
        self,
        *,
        entries: dict[str, PromptCatalogEntry],
        catalog_path: Path,
        root_dir: Path,
        strict: bool,
        audit_dir: Path,
    ) -> None:
        self._entries = entries
        self._catalog_path = catalog_path
        self._root_dir = root_dir
        self._strict = strict
        self._cache: dict[str, _CachedPrompt] = {}
        self._audit_dir = audit_dir

    @property
    def strict(self) -> bool:
        return self._strict

    @property
    def entries(self) -> dict[str, PromptCatalogEntry]:
        return dict(self._entries)

    def get_prompt(self, prompt_id: str) -> PromptAsset:
        entry = self._entries.get(prompt_id)
        if entry is None:
            raise PromptRegistryError(f"unknown prompt id: {prompt_id}")
        if entry.type != "prompt":
            raise PromptTypeMismatchError(f"id {prompt_id} is type={entry.type}, expected prompt")
        if entry.path is None:
            raise PromptRegistryError(f"prompt {prompt_id} missing path")
        path = self._resolve_path(entry.path)
        return self._load_prompt_asset(prompt_id, path)

    def get_profile(self, profile_id: str) -> PromptProfile:
        entry = self._entries.get(profile_id)
        if entry is None:
            raise PromptRegistryError(f"unknown profile id: {profile_id}")
        if entry.type != "profile":
            raise PromptTypeMismatchError(f"id {profile_id} is type={entry.type}, expected profile")
        members = list(entry.members or [])
        if not members:
            raise PromptRegistryError(f"profile {profile_id} has empty members")
        return PromptProfile(
            id=entry.id,
            members=members,
            status=entry.status,
            binding_reason_template=entry.binding_reason_template,
        )

    def resolve_profile(self, profile_id: str) -> list[PromptAsset]:
        profile = self.get_profile(profile_id)
        assets: list[PromptAsset] = []
        for member_id in profile.members:
            member = self._entries.get(member_id)
            if member is None:
                raise PromptRegistryError(f"profile {profile_id} references unknown member: {member_id}")
            if member.type != "prompt":
                raise PromptRegistryError(
                    f"profile {profile_id} member must be prompt, got {member_id}:{member.type}"
                )
            assets.append(self.get_prompt(member_id))
        return assets

    def _resolve_path(self, rel_or_abs: str) -> Path:
        p = Path(rel_or_abs)
        if p.is_absolute():
            return p
        return (self._root_dir / p).resolve()

    def _load_prompt_asset(self, prompt_id: str, path: Path) -> PromptAsset:
        if not path.exists():
            raise PromptRegistryError(f"prompt file not found for {prompt_id}: {path}")

        stat = path.stat()
        cached = self._cache.get(prompt_id)
        if cached and (
            cached.asset.mtime_ns == stat.st_mtime_ns
            and cached.asset.size == stat.st_size
            and cached.asset.inode == stat.st_ino
        ):
            return cached.asset

        text = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        asset = PromptAsset(
            id=prompt_id,
            path=path,
            text=text,
            sha256=digest,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            inode=stat.st_ino,
        )
        self._cache[prompt_id] = _CachedPrompt(asset=asset)
        return asset


def compose_binding_hash(prompt_assets: list[PromptAsset]) -> str:
    normalized = sorted((p.id, p.sha256) for p in prompt_assets)
    payload = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _emit_strict_disabled_event(audit_dir: Path) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "event_type": "prompt_registry_strict_disabled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "caller": inspect.stack()[2].function if len(inspect.stack()) > 2 else "unknown",
        "cwd": str(Path.cwd()),
        "ci": _to_bool_env("CI", False),
        "pid": os.getpid(),
    }
    path = audit_dir / "prompt_registry_events.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=True) + "\n")


def load_catalog(
    path: str | Path,
    *,
    strict: bool | None = None,
    root_dir: str | Path | None = None,
    audit_dir: str | Path | None = None,
) -> PromptRegistry:
    catalog_path = Path(path).resolve()
    if not catalog_path.exists():
        raise PromptRegistryError(f"prompt catalog not found: {catalog_path}")

    effective_strict = _to_bool_env("AGORA_PROMPT_STRICT", True) if strict is None else strict
    if _to_bool_env("CI", False) and not effective_strict:
        raise PromptRegistryError("AGORA_PROMPT_STRICT=false is forbidden in CI")

    root = Path(root_dir).resolve() if root_dir is not None else catalog_path.parent.parent.resolve()
    audit = Path(audit_dir).resolve() if audit_dir is not None else (root / "governance" / "audits")
    if not effective_strict:
        _emit_strict_disabled_event(audit)

    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    entries_payload = payload.get("entries", [])
    if not isinstance(entries_payload, list):
        raise PromptRegistryError("prompt catalog entries must be a list")

    entries: dict[str, PromptCatalogEntry] = {}
    for raw in entries_payload:
        if not isinstance(raw, dict):
            raise PromptRegistryError("each prompt catalog entry must be an object")
        entry_id = str(raw.get("id", "")).strip()
        if not entry_id:
            raise PromptRegistryError("catalog entry missing id")
        if entry_id in entries:
            raise PromptRegistryError(f"duplicate catalog id: {entry_id}")

        entry_type = str(raw.get("type", "")).strip()
        if entry_type not in {"prompt", "profile"}:
            raise PromptRegistryError(f"entry {entry_id} has invalid type: {entry_type}")

        status = str(raw.get("status", "active")).strip()
        if status not in {"active", "disabled"}:
            raise PromptRegistryError(f"entry {entry_id} has invalid status: {status}")

        if entry_type == "prompt":
            path_value = str(raw.get("path", "")).strip()
            if not path_value:
                raise PromptRegistryError(f"prompt entry {entry_id} missing path")
            resolved = Path(path_value)
            if not resolved.is_absolute():
                resolved = (root / resolved).resolve()
            if effective_strict and not resolved.exists():
                raise PromptRegistryError(f"prompt file missing for {entry_id}: {resolved}")
            entries[entry_id] = PromptCatalogEntry(
                id=entry_id,
                type="prompt",
                path=path_value,
                status=status,
                default_enabled=bool(raw.get("default_enabled", True)),
                requires_authorization=raw.get("requires_authorization"),
            )
            continue

        members = raw.get("members")
        if not isinstance(members, list) or not members:
            raise PromptRegistryError(f"profile {entry_id} must define non-empty members")
        member_ids = [str(x).strip() for x in members if str(x).strip()]
        if len(member_ids) != len(members):
            raise PromptRegistryError(f"profile {entry_id} contains empty member id")
        entries[entry_id] = PromptCatalogEntry(
            id=entry_id,
            type="profile",
            status=status,
            members=member_ids,
            binding_reason_template=raw.get("binding_reason_template"),
            default_enabled=bool(raw.get("default_enabled", True)),
            requires_authorization=raw.get("requires_authorization"),
        )

    # second pass: validate profile member references
    for entry in entries.values():
        if entry.type != "profile":
            continue
        assert entry.members is not None
        for member_id in entry.members:
            member = entries.get(member_id)
            if member is None:
                raise PromptRegistryError(f"profile {entry.id} member not found: {member_id}")
            if member.type != "prompt":
                raise PromptRegistryError(
                    f"profile {entry.id} member must be prompt, got {member_id}:{member.type}"
                )

    return PromptRegistry(
        entries=entries,
        catalog_path=catalog_path,
        root_dir=root,
        strict=effective_strict,
        audit_dir=audit,
    )

