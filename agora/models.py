from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import field_validator


class TaskFeatures(BaseModel):
    """Normalized task features consumed by deterministic routing rules."""

    model_config = ConfigDict(strict=True, extra="forbid")

    task_intent: Literal["code_review", "research", "planning", "general", "unknown"]
    risk_level: Literal["low", "medium", "high"]
    reversibility: Literal["reversible", "partial", "irreversible"]
    requires_tools: bool
    confidence: float = Field(ge=0.0, le=1.0)


FALLBACK_FEATURES = TaskFeatures(
    task_intent="unknown",
    risk_level="medium",
    reversibility="partial",
    requires_tools=False,
    confidence=0.0,
)


class DecisionStatus(str, Enum):
    FINAL = "FINAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    SUSPEND_DECISION = "SUSPEND_DECISION"


class VerificationOutcome(str, Enum):
    CONFIRMED = "confirmed"
    NEGATED = "negated"
    UNCERTAIN = "uncertain"
    INFRA_ERROR = "infra_error"
    NEW_HYPOTHESIS = "new_hypothesis"


class WorkflowContext(BaseModel):
    """Minimum context required to determine decision status."""

    model_config = ConfigDict(strict=True, extra="forbid")

    risk_level: Literal["low", "medium", "high"]
    verification_outcome: VerificationOutcome
    hypothesis_rounds: int = Field(ge=0)
    max_hypothesis_rounds: int = Field(default=2, ge=0)
    semantic_gate_passed: bool
    structural_gate_passed: bool


class RoutingDecision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_type: str
    permissions_scope: str
    debate_triggered: bool
    fallback_chain: list[str]
    matched_rule: str
    feature_confidence: float


class FallbackEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    primary_model: str
    error_class: str
    switchover_model: str
    recovery_status: Literal["pending", "recovered", "failed"]
    timestamp: datetime


class AuditAppendRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    component_id: str
    key_id: str
    hmac_sig: str
    event_id: str
    event_type: str
    payload: dict
    trace_id: str = "trace-unknown"
    timestamp: datetime

    @field_validator("timestamp", mode="before")
    @classmethod
    def _coerce_timestamp(cls, value: object) -> object:
        if isinstance(value, str):
            s = value
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        return value


class AuditEvent(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    event_id: str
    seq_no: int = Field(ge=1)
    timestamp: datetime
    component_id: str
    event_type: str
    payload: dict
    trace_id: str


class HealthSnapshot(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    audit_state: Literal["normal", "degraded", "readonly"]
    degraded_since: str | None
    degraded_seconds: int = Field(ge=0)
    normal_since: str | None
    normal_seconds: int = Field(ge=0)
    degraded_request_count: int = Field(ge=0)
    pending_wal_events: int = Field(ge=0)
    wal_size_bytes: int = Field(ge=0)
    recovery_cooldown_seconds: int = Field(ge=0)
    budget_exceeded: bool
    last_updated: str | None = None
    last_refresh_cause: str | None = None


class AuditAppendResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    accepted: bool
    duplicate: bool
    seq_no: int | None
    wrote_to_wal: bool
    durability_mode: Literal["audit", "wal"]
    audit_state: Literal["normal", "degraded", "readonly"]
    health_snapshot: HealthSnapshot


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolActionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    workflow_id: str
    action_id: str
    action: str
    risk_level: Literal["low", "medium", "high"]
    reversible: bool
    idempotent: bool
    approval_required: bool = False
    payload: dict = Field(default_factory=dict)


class ToolAuthorizationResult(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    allowed: bool
    reason: str
    approval_state: ApprovalState | None = None


class SessionBudget(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    max_cost_usd: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = Field(default=None, ge=0)
    consumed_cost_usd: float = Field(default=0.0, ge=0.0)
    consumed_tokens: int = Field(default=0, ge=0)


class SessionQuota(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    max_messages_per_minute: int = Field(default=0, ge=0)
    window_seconds: int = Field(default=60, ge=1)
