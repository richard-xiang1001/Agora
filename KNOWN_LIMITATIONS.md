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

## Operator Guidance
- Use this system for auditable analysis workflows, not autonomous high-risk execution.
- Treat Week 1 outputs as controlled pilot artifacts for failure-driven iteration.

## Week 6 Limits Update
- Red-team suite is currently deterministic and fixture-driven; it is not yet fed by large-scale production traffic replay.
- Release gate automation creates incident stubs for soft failures, but escalation policy still depends on correct incident metadata quality.
- Test-stage API invocation is constrained to `:free` models only; model behavior under paid/SOTA providers is intentionally out of scope for current validation.
