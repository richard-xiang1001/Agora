from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    session_id: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionBudgetRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    max_cost_usd: float | None = Field(default=None, ge=0.0)
    max_tokens: int | None = Field(default=None, ge=0)


class SessionBudgetView(BaseModel):
    max_cost_usd: float | None = None
    max_tokens: int | None = None
    consumed_cost_usd: float = 0.0
    consumed_tokens: int = 0
    remaining_cost_usd: float | None = None
    remaining_tokens: int | None = None


class SessionBudgetResponse(BaseModel):
    session_id: str
    budget: SessionBudgetView


class MessageAuthorization(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    requested_domains: list[str] | None = None


class MessageRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_text: str = Field(min_length=1)
    raw_features: dict[str, Any] | None = None
    subagent_disagreement: bool = False
    authorization: MessageAuthorization | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    cancel_after_round: int | None = Field(default=None, ge=1, le=3)


class MessageResponse(BaseModel):
    workflow_id: str
    session_id: str
    workflow_type: str
    permissions_scope: str
    debate_triggered: bool
    matched_rule: str
    audit_status: str
    degradation_policy: str
    trace_id: str
    prompt_profile_id: str | None = None
    prompt_binding_hash: str | None = None
    verdict: dict[str, Any] | None = None
    debate_verdict: dict[str, Any] | None = None
    execution_mode: str | None = None
    idempotency_hit: bool = False
    workflow_status: str | None = None
    cancelled_at_round: int | None = None


class RoutePreviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_text: str = ""
    raw_features: dict[str, Any] | None = None
    subagent_disagreement: bool = False


class ToolApproveRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    workflow_id: str
    action_id: str
    approved: bool
    operator_id: str | None = None


class ToolDispatchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    workflow_id: str
    scope: str
    action_id: str
    action: str
    risk_level: Literal["low", "medium", "high"]
    reversible: bool
    idempotent: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = "trace-local"


class IncidentCreateRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    incident_id: str | None = None
    severity: str
    test_category: str
    trigger: str
    root_cause: str
    affected_components: list[str]
    due_date: str | None = None
