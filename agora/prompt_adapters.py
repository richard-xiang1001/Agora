from __future__ import annotations

from pathlib import Path
from typing import Literal


OutputMode = Literal["markdown_claim_v1", "json_claim_v1"]


def load_json_claim_contract(root_dir: str | Path = ".") -> str:
    path = Path(root_dir) / "prompt_lab" / "templates" / "json_claim_v1_contract.md"
    return path.read_text(encoding="utf-8").strip()


def compose_subagent_prompt(
    *,
    base_prompt: str,
    domain_prompt: str,
    output_mode: OutputMode,
    root_dir: str | Path = ".",
) -> str:
    parts = [base_prompt.strip(), "## Domain-Specific Lens", domain_prompt.strip()]
    if output_mode == "json_claim_v1":
        parts.extend(["", load_json_claim_contract(root_dir)])
    return "\n\n".join(parts).strip()

