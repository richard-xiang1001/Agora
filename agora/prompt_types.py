from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PromptEntryType = Literal["prompt", "profile"]
PromptStatus = Literal["active", "disabled"]


@dataclass(frozen=True)
class PromptCatalogEntry:
    id: str
    type: PromptEntryType
    status: PromptStatus
    path: str | None = None
    default_enabled: bool = True
    requires_authorization: str | None = None
    members: list[str] | None = None
    binding_reason_template: str | None = None


@dataclass(frozen=True)
class PromptAsset:
    id: str
    path: Path
    text: str
    sha256: str
    mtime_ns: int
    size: int
    inode: int


@dataclass(frozen=True)
class PromptProfile:
    id: str
    members: list[str]
    status: PromptStatus
    binding_reason_template: str | None = None

