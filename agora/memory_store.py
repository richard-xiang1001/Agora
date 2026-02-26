from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agora.model_registry import load_model_family_map, resolve_model_identity

MemoryState = Literal["active", "stale", "expired"]


class MemoryProfile(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    model_id: str
    model_version: str
    model_family: str
    task_type: str
    state: MemoryState
    created_at: datetime
    ttl_days: int = Field(ge=1)
    expires_at: datetime
    last_updated: datetime
    confidence_score: float = Field(ge=0.0, le=1.0)
    summary: str

    @field_validator("created_at", "expires_at", "last_updated", mode="before")
    @classmethod
    def _coerce_dt(cls, value: object) -> object:
        if isinstance(value, str):
            s = value
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        return value

    def weight_multiplier(self) -> float:
        if self.state == "active":
            return 1.0
        if self.state == "stale":
            return 0.5
        return 0.0


@dataclass(frozen=True)
class MemoryQueryResult:
    profile: MemoryProfile | None
    priority: str


class MemoryStore:
    def __init__(self, memory_dir: str | Path, model_family_map_path: str | Path | None = None) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.model_family_map = (
            load_model_family_map(model_family_map_path)
            if model_family_map_path
            else {}
        )

    def upsert_profile(
        self,
        *,
        model_id: str,
        task_type: str,
        summary: str,
        ttl_days: int,
        confidence_score: float,
        now: datetime | None = None,
    ) -> MemoryProfile:
        now = now or datetime.now(timezone.utc)
        identity = resolve_model_identity(model_id, self.model_family_map)
        profile = MemoryProfile(
            model_id=model_id,
            model_version=identity.version,
            model_family=identity.family,
            task_type=task_type,
            state="active",
            created_at=now,
            ttl_days=ttl_days,
            expires_at=now + timedelta(days=ttl_days),
            last_updated=now,
            confidence_score=confidence_score,
            summary=summary,
        )
        self.save_profile(profile)
        return profile

    def save_profile(self, profile: MemoryProfile) -> Path:
        path = self._profile_path(profile)
        front = yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=False)
        content = f"---\n{front}---\n{profile.summary.rstrip()}\n"
        path.write_text(content, encoding="utf-8")
        return path

    def load_profiles(self) -> list[MemoryProfile]:
        out: list[MemoryProfile] = []
        for path in sorted(self.memory_dir.glob("*_profile.md")):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---\n"):
                continue
            _, rest = text.split("---\n", 1)
            fm, body = rest.split("---\n", 1)
            data = yaml.safe_load(fm)
            if not isinstance(data, dict):
                continue
            data["summary"] = body.strip()
            out.append(MemoryProfile(**data))
        return out

    def query(self, *, model_version: str, task_type: str) -> MemoryQueryResult:
        profiles = self.load_profiles()

        def pick(state: MemoryState, same_task: bool | None = None) -> MemoryProfile | None:
            for p in profiles:
                if p.model_version != model_version:
                    continue
                if p.state != state:
                    continue
                if same_task is True and p.task_type != task_type:
                    continue
                if same_task is False and p.task_type == task_type:
                    continue
                return p
            return None

        p = pick("active", same_task=True)
        if p:
            return MemoryQueryResult(p, "active_same_version_same_task")

        p = pick("active", same_task=False)
        if p:
            return MemoryQueryResult(p, "active_same_version_cross_task")

        p = pick("stale", same_task=None)
        if p:
            return MemoryQueryResult(p, "stale_same_version")

        return MemoryQueryResult(None, "none")

    def apply_ttl_transitions(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        changed = 0
        profiles = self.load_profiles()
        for p in profiles:
            stale_after = p.expires_at
            expired_after = p.expires_at + timedelta(days=p.ttl_days)
            new_state = p.state
            if now <= stale_after:
                new_state = "active"
            elif stale_after < now <= expired_after:
                new_state = "stale"
            elif now > expired_after:
                new_state = "expired"

            if new_state != p.state:
                p.state = new_state
                p.last_updated = now
                self.save_profile(p)
                changed += 1
        return changed

    def on_model_version_change(self, old_version: str, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        changed = 0
        for p in self.load_profiles():
            if p.model_version == old_version and p.state == "active":
                p.state = "stale"
                p.last_updated = now
                self.save_profile(p)
                changed += 1
        return changed

    def build_index(self) -> dict[str, dict[str, list[str]]]:
        index: dict[str, dict[str, list[str]]] = {}
        for p in self.load_profiles():
            by_version = index.setdefault(p.model_version, {})
            arr = by_version.setdefault(p.task_type, [])
            arr.append(self._profile_path(p).name)
        return index

    def _profile_path(self, profile: MemoryProfile) -> Path:
        name = f"{profile.model_id}_{profile.model_version}_{profile.task_type}_profile.md"
        safe = name.replace("/", "_")
        return self.memory_dir / safe
