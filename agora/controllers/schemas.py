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


class SessionBudgetPolicyRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    on_exceeded: Literal["block", "degrade_to_mock", "allow_with_audit"]
    degrade_model: str = "mock"
    grace_requests: int = Field(default=0, ge=0)


class SessionBudgetPolicyView(BaseModel):
    on_exceeded: Literal["block", "degrade_to_mock", "allow_with_audit"]
    degrade_model: str = "mock"
    grace_requests: int = 0
    grace_used: int = 0


class SessionBudgetPolicyResponse(BaseModel):
    session_id: str
    budget_policy: SessionBudgetPolicyView


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
    budget_policy_applied: Literal["none", "block", "degrade_to_mock", "allow_with_audit"] = "none"
    degraded_execution: bool = False
    runtime_mode: Literal["request_driven", "queued_runtime"] = "request_driven"
    initiative_status: Literal["none", "proposed", "approved", "blocked", "executed"] = "none"
    memory_write_events: int = 0


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


class RuntimeStartResponse(BaseModel):
    running: bool
    queue_depth: int
    recovered_tasks: int = 0


class RuntimeStopResponse(BaseModel):
    running: bool


class RuntimeStatusResponse(BaseModel):
    running: bool
    queue_depth: int
    active_task_id: str | None = None
    processed_count: int = 0


class RuntimeTaskRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    command_text: str = Field(min_length=1)
    raw_features: dict[str, Any] | None = None
    subagent_disagreement: bool = False
    authorization: MessageAuthorization | None = None
    request_id: str | None = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    cancel_after_round: int | None = Field(default=None, ge=1, le=3)


class RuntimeTaskEnqueueResponse(BaseModel):
    task_id: str
    session_id: str
    status: Literal["queued", "running", "waiting_user", "cancelled", "completed", "failed"]


class RuntimeTaskStatusResponse(BaseModel):
    task_id: str
    session_id: str
    status: Literal["queued", "running", "waiting_user", "cancelled", "completed", "failed"]
    workflow_id: str | None = None
    error: str | None = None
    response: dict[str, Any] | None = None


class InitiativePolicyRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    mode: Literal["manual_confirm", "suggest_only", "auto_low_risk"] = "suggest_only"
    max_auto_actions_per_hour: int = Field(default=3, ge=0)
    require_human_on_budget_exceeded: bool = True


class InitiativePolicyView(BaseModel):
    mode: Literal["manual_confirm", "suggest_only", "auto_low_risk"]
    max_auto_actions_per_hour: int
    require_human_on_budget_exceeded: bool


class InitiativePolicyResponse(BaseModel):
    session_id: str
    initiative_policy: InitiativePolicyView


class MemoryIngestRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    layer: Literal["episodic", "semantic", "procedural"]
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


class MemoryIngestResponse(BaseModel):
    session_id: str
    inserted: bool
    record_id: str
    layer: Literal["episodic", "semantic", "procedural"]


class MemoryQueryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class MemoryQueryHit(BaseModel):
    record_id: str
    layer: Literal["episodic", "semantic", "procedural"]
    score: float
    content: str
    hit_path: str


class MemoryQueryResponse(BaseModel):
    session_id: str
    hits: list[MemoryQueryHit]


class MemoryDecayResponse(BaseModel):
    session_id: str
    decayed_count: int


class MemoryStatsResponse(BaseModel):
    session_id: str
    by_layer: dict[str, int]
    total: int
