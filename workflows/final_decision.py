from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FinalDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    status: Literal["FINAL", "NEEDS_REVIEW", "SUSPEND_DECISION"]
    final_answer: str
    evidence_sources: list[str] = Field(min_length=1)
    confidence_label: Literal["high", "medium", "low", "speculative"]
    core_assumptions: list[str] = Field(min_length=1)
    uncertainties: list[str] = Field(min_length=1)
    minority_view: str | None = None
    evidence_independence_check: bool
    verification_outcome: Literal[
        "confirmed", "negated", "uncertain", "infra_error", "new_hypothesis"
    ]
    suspend_reason: str | None = None
    required_human_action: str | None = None

    @model_validator(mode="after")
    def _check_suspend_fields(self) -> "FinalDecision":
        if self.status == "SUSPEND_DECISION":
            if not self.suspend_reason:
                raise ValueError("suspend_reason required when status is SUSPEND_DECISION")
            if not self.required_human_action:
                raise ValueError(
                    "required_human_action required when status is SUSPEND_DECISION"
                )
        return self
