# Agora

Agora is a local-first, auditable code-review orchestration system with deterministic routing, prompt profile binding, subagent/debate execution, and append-only audit logging.

## Architecture (Week9)

- `agora/api.py`: app bootstrap + router mounting only.
- `agora/routes/`: FastAPI route registration (`sessions`, `workflows`, `internal`, `admin`).
- `agora/controllers/`: request orchestration (idempotency, budget/rate-limit checks, cancel).
- `agora/services/`: framework-agnostic helpers (routing, execution, audit wrappers).

## Architecture (Week10)

- `agora/debate_executor.py`: compatibility facade; round logic split to `agora/debate/`.
- `agora/llm_client.py`: compatibility facade; provider/policy/cost/backoff split to `agora/llm/`.
- Session budget policy supports `block | degrade_to_mock | allow_with_audit`.

## Architecture (Week11)

- Added local runtime loop with queue + checkpoint recovery:
  - `POST /v1/runtime/start|stop`, `GET /v1/runtime/status`
  - `POST /v1/sessions/{id}/tasks`, `GET /v1/sessions/{id}/tasks/{task_id}`
- Added memory v2 layered store (`episodic|semantic|procedural`) with ingest/query/decay/stats APIs.
- Added initiative policy (`manual_confirm|suggest_only|auto_low_risk`) and auditable initiative status.

## Quickstart (Mock, 30 minutes)

### 1) Create venv and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Run core contract tests

```bash
make test-mock
```

### 3) Run debate CLI in mock mode

```bash
python3 scripts/run_debate.py --diff "fix: remove unused import" --mock
```

### 4) Run prompt embedding gates

```bash
bash scripts/run_prompt_embedding_gate.sh
bash scripts/run_prompt_embedding_live_gate.sh --dry-run
bash scripts/run_prompt_embedding_completion_gate.sh --dry-run
```

## Live mode (requires OpenRouter key)

```bash
export OPENROUTER_API_KEY='sk-or-v1-...'
python3 scripts/openrouter_healthcheck.py --mode live
make test-live
```

## Common commands

```bash
make test-mock
make test-live
make gate-week8
make gate-week9
make test-adversarial
make bench-quality
make check-budget
make gate-week10
make gate-week11
```

## Internal API auth

`/internal/*` endpoints require header `X-Agora-Internal-Token`.
Set env before calling:

```bash
export AGORA_INTERNAL_API_TOKEN='your-internal-token'
```

## Known limitations

See `KNOWN_LIMITATIONS.md` for current boundary conditions and accepted risks.
