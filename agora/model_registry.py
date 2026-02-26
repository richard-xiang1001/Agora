from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ModelIdentity:
    model_id: str
    family: str
    version: str


def load_model_family_map(path: str | Path) -> dict[str, dict[str, str]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return payload.get("model_family_map", {})


def resolve_model_identity(model_id: str, mapping: dict[str, dict[str, str]]) -> ModelIdentity:
    if model_id not in mapping:
        raise KeyError(f"model_id not found in family map: {model_id}")
    row = mapping[model_id]
    return ModelIdentity(model_id=model_id, family=row["family"], version=row["version"])
