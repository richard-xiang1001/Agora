from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agora.models import DecisionStatus, VerificationOutcome, WorkflowContext


@dataclass(frozen=True)
class VerificationDecision:
    action: str
    status: DecisionStatus | None
    reason: str | None = None
    retry_after_seconds: int | None = None


class VerificationEngine:
    """Week 3 verification outcome routing with bounded retries and hypothesis depth."""

    def __init__(self, max_retries: int = 2, retry_delay_seconds: int = 2, max_parallel: int = 8) -> None:
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.max_parallel = max_parallel

    def route_outcome(
        self,
        context: WorkflowContext,
        outcome: VerificationOutcome,
        retry_count: int,
        active_parallel: int,
    ) -> VerificationDecision:
        if outcome in {VerificationOutcome.CONFIRMED, VerificationOutcome.NEGATED}:
            status = self._final_status(context)
            return VerificationDecision(action="finalize", status=status)

        if outcome == VerificationOutcome.UNCERTAIN:
            if context.risk_level == "high":
                return VerificationDecision(
                    action="suspend",
                    status=DecisionStatus.SUSPEND_DECISION,
                    reason="high_risk_unverifiable",
                )
            return VerificationDecision(action="review", status=DecisionStatus.NEEDS_REVIEW)

        if outcome == VerificationOutcome.INFRA_ERROR:
            if retry_count < self.max_retries and active_parallel < self.max_parallel:
                return VerificationDecision(
                    action="retry",
                    status=None,
                    reason="infra_error_retry",
                    retry_after_seconds=self.retry_delay_seconds,
                )
            if context.risk_level == "high":
                return VerificationDecision(
                    action="suspend",
                    status=DecisionStatus.SUSPEND_DECISION,
                    reason="infra_error_retry_exhausted",
                )
            return VerificationDecision(
                action="review",
                status=DecisionStatus.NEEDS_REVIEW,
                reason="infra_error_retry_exhausted",
            )

        # NEW_HYPOTHESIS
        if context.hypothesis_rounds + 1 > context.max_hypothesis_rounds:
            return VerificationDecision(
                action="suspend",
                status=DecisionStatus.SUSPEND_DECISION,
                reason="hypothesis_depth_exceeded",
            )
        return VerificationDecision(action="debate_incremental", status=None)

    @staticmethod
    def _final_status(context: WorkflowContext) -> DecisionStatus:
        if context.semantic_gate_passed and context.structural_gate_passed:
            return DecisionStatus.FINAL
        return DecisionStatus.NEEDS_REVIEW


async def create_sandbox_manifest(base_dir: str | Path, workflow_id: str) -> Path:
    root = Path(base_dir) / workflow_id
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "workflow_id": workflow_id,
        "status": "active",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
    }
    manifest = root / "sandbox_manifest.json"
    await asyncio.to_thread(manifest.write_text, json.dumps(payload, indent=2), "utf-8")
    return manifest


async def update_sandbox_manifest(
    manifest_path: str | Path,
    status: str,
    heartbeat_only: bool = False,
) -> None:
    path = Path(manifest_path)

    def _update() -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not heartbeat_only:
            data["status"] = status
        data["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    await asyncio.to_thread(_update)
