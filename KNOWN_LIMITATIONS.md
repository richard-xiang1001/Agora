# KNOWN_LIMITATIONS (v7.1 Week 1)

## Scope Boundaries
- This system is single-tenant and local-first in Week 1; it is not a multi-tenant platform.
- Week 1 only supports MVW-A (read-only code review). No patch writing or code execution is allowed.
- Unknown-intent routing is intentionally restrictive and may over-reject.

## Not Suitable For
- Low-latency real-time decisioning where debate/verification latency is unacceptable.
- Long-running continuous conversations that require persistent interactive memory beyond session files.
- Security validation requiring production-like external infrastructure.

## Failure Modes
- Missing or unstable model structured output can cause fallback to `unknown` route.
- If audit subsystem is unavailable, system enters degraded mode with WAL buffering.
- High-risk unresolved conflicts may return `SUSPEND_DECISION` and require human review.
- Audit degradation budget state is persisted by AuditDaemon (`audit/health_state.json`), and reset only after sustained normal mode plus empty WAL; API process restarts do not reset budget.

## Operator Guidance
- Use this system for auditable analysis workflows, not autonomous high-risk execution.
- Treat Week 1 outputs as controlled pilot artifacts for failure-driven iteration.

## Week 6 Limits Update
- Red-team suite is currently deterministic and fixture-driven; it is not yet fed by large-scale production traffic replay.
- Release gate automation creates incident stubs for soft failures, but escalation policy still depends on correct incident metadata quality.
- Test-stage API invocation is constrained to `:free` models only; model behavior under paid/SOTA providers is intentionally out of scope for current validation.

## L3 Isolation Status
- Current L3 mode: `docker_compose` (`l3_isolation_mode=docker_compose`).
- Sandbox verification remains guarded by policy (`allow_sandbox_verification_without_l3=false`).
- Accepted risk: single-host deployment assumptions still apply; multi-host consistency is not covered.
- Exit criteria: distributed-safe coordination and multi-host runtime verification are implemented.

## Workflow Cancel Semantics
- Cancel is cooperative and becomes effective at debate round boundaries.
- A single in-flight external LLM call cannot be force-killed; cancellation may be delayed until timeout/checkpoint.
- `cancel_after_round` reuses cooperative cancellation checkpoints (round-boundary only).

## Week9 Runtime Limits
- Session request rate limiting is process-memory based (`session_quota` window counters) and resets on process restart.
- Cost budget enforcement is session-local and file-backed; multi-host shared budget consistency is not implemented.
- `api.py` has been split into routes/controllers/services, but `debate_executor.py` and `llm_client.py` remain large and are deferred for the next refactor cycle.

## Week10 Runtime Limits
- Debate/LLM layers are split into facade + module internals; distributed cancellation semantics remain unchanged (cooperative only).
- Budget policy (`block|degrade_to_mock|allow_with_audit`) is session-local and file-backed, still single-host consistency only.
- Runtime stability benchmark is local mock-based; it is a release gate signal, not a substitute for production traffic replay.

## Week11 Runtime/Memory/Initiative Limits
- Runtime loop persistence is local-file based (`runtime/task_queue.jsonl` + `runtime/checkpoint.json`); multi-host coordination is still out of scope.
- Memory v2 is file-backed and lexical retrieval based; no external vector index is used in this phase.
- Initiative `auto_low_risk` is conservative and constrained by local policy only; no cross-session/global quota coordination.

## Week7 Risk Registry
- R-06: Red-team remains fixture-driven and does not yet replay anonymized production traffic distribution.
- R-08: Multi-instance budget persistence requires externalized state (Redis/etcd) and is not implemented.
- R-09: Paid/SOTA provider behavior remains unvalidated under current free-only test policy.
- R-10: Cross-host deployment invalidates single-writer local file assumptions and needs distributed coordination.
- R-11: Single-tenant boundary remains in effect; no tenant namespace isolation is implemented.

<!-- WEEK7_LIMITATIONS_BEGIN -->
week7_limitations:
  multi_instance_budget_externalization:
    first_seen_on: "2026-02-28"
    verified_on: "2026-02-28"
    reviewed_by: "maintainer"
    review_note: "Reviewed: local-file budget persistence is still single-node only."
  paid_sota_coverage_gap:
    first_seen_on: "2026-02-28"
    verified_on: "2026-02-28"
    reviewed_by: "maintainer"
    review_note: "Reviewed: free-only policy still active in acceptance scripts."
  cross_host_single_writer_risk:
    first_seen_on: "2026-02-28"
    verified_on: "2026-02-28"
    reviewed_by: "maintainer"
    review_note: "Reviewed: audit single-writer constraint is local-host scoped."
  single_tenant_limit:
    first_seen_on: "2026-02-28"
    verified_on: "2026-02-28"
    reviewed_by: "maintainer"
    review_note: "Reviewed: no tenant isolation layer or tenant-scoped namespaces exist."
  redteam_replay_gap:
    first_seen_on: "2026-02-28"
    verified_on: "2026-02-28"
    reviewed_by: "maintainer"
    review_note: "Reviewed: red-team suite remains fixture corpus driven."
<!-- WEEK7_LIMITATIONS_END -->
