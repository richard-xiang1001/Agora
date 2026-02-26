# Release Gate Runbook (Week 6)

## Inputs
- Red-team report: `governance/redteam/report_week6.json`
- Threshold policy: `redteam/thresholds.yaml`
- Incident backlog: `incidents/*.yaml`

## Execution Order
1. Run red-team suite (`scripts/run_redteam_suite.py`).
2. Run fault storm drill (`scripts/run_fault_storm_drill.py`).
3. Run release gate (`scripts/run_release_gate.py`).

## Decision Rules
- Hard-constraint category below 100%: release blocked.
- Soft-threshold miss: release allowed with incident auto-created and due-date set.
- Overdue incidents escalate same test-category threshold to 100%.

## Outputs
- `governance/redteam/release_gate_week6.json`
- Auto-created incident stubs in `incidents/` for soft failures.

## Free-Model Test Policy
- All API-based test paths must run with `:free` model IDs only.
- Enforcement script: `scripts/check_free_model_policy.py`.
