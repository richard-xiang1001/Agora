from __future__ import annotations

from pathlib import Path
from typing import Literal

from agora.fileio import SessionLockManager, atomic_write

Round3Mode = Literal["consensus", "majority_with_minority", "suspend"]


class DebateEngine:
    """File-driven 3-round debate engine for Week 3 MVP."""

    def __init__(self, lock_manager: SessionLockManager | None = None) -> None:
        self._lock_manager = lock_manager or SessionLockManager()

    async def round1_parallel_claims(self, session_dir: str | Path, claims: dict[str, str]) -> Path:
        session = Path(session_dir)
        claims_dir = session / "claims"
        debate_dir = session / "debate"
        debate_dir.mkdir(parents=True, exist_ok=True)

        async with self._lock_manager.locked(str(session)):
            for agent_id, text in claims.items():
                await atomic_write(claims_dir / f"{agent_id}.md", text.rstrip() + "\n")

            lines = ["# Debate Round 1", "", "## Parallel Claims"]
            for agent_id in sorted(claims):
                lines.append(f"- {agent_id}: claims/{agent_id}.md")
            lines.append("")
            round_path = debate_dir / "round_1.md"
            await atomic_write(round_path, "\n".join(lines))
            return round_path

    async def round2_cross_critique(self, session_dir: str | Path, critiques: dict[str, str]) -> Path:
        session = Path(session_dir)
        debate_dir = session / "debate"
        debate_dir.mkdir(parents=True, exist_ok=True)

        lines = ["# Debate Round 2", "", "## Cross Critiques"]
        for agent_id, text in sorted(critiques.items()):
            lines.extend([f"### {agent_id}", text.strip(), ""])

        round_path = debate_dir / "round_2.md"
        async with self._lock_manager.locked(str(session)):
            await atomic_write(round_path, "\n".join(lines).rstrip() + "\n")
        return round_path

    async def round3_converge(
        self,
        session_dir: str | Path,
        mode: Round3Mode,
        summary: str,
        minority_view: str | None = None,
    ) -> Path:
        session = Path(session_dir)
        debate_dir = session / "debate"
        debate_dir.mkdir(parents=True, exist_ok=True)

        lines = ["# Debate Round 3", "", f"mode: {mode}", "", "## Summary", summary.strip(), ""]
        if mode == "majority_with_minority":
            lines.extend(["## Minority View", (minority_view or "(missing)").strip(), ""])
        if mode == "suspend":
            lines.extend([
                "## Decision",
                "SUSPEND_DECISION",
                "Insufficient verifiable evidence; human review required.",
                "",
            ])

        round_path = debate_dir / "round_3.md"
        async with self._lock_manager.locked(str(session)):
            await atomic_write(round_path, "\n".join(lines).rstrip() + "\n")
        return round_path
