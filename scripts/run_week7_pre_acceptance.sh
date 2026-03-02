#!/usr/bin/env bash
set -euo pipefail

AUDITS_DIR="governance/audits"
mkdir -p "${AUDITS_DIR}"
RESULTS_FILE="${AUDITS_DIR}/week7_test_results.jsonl"
rm -f "${RESULTS_FILE}"

echo "[Init] week7 runtime context"
python3 - <<'PY'
import datetime as dt
import json
import pathlib
import uuid

out = pathlib.Path("governance/audits/week7_runtime_context.json")
out.parent.mkdir(parents=True, exist_ok=True)
payload = {
    "run_id": f"week7-{uuid.uuid4().hex[:12]}",
    "t0": dt.datetime.now(dt.timezone.utc).isoformat(),
    "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
}
out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
print(f"[PASS] wrote {out}")
PY
python3 scripts/lint_week7_runtime_context.py

record_result() {
  local test_name="$1"
  local status="$2"
  local notes="${3:-}"
  local workflow_ids_json="${4:-[]}"
  TEST_NAME="${test_name}" TEST_STATUS="${status}" TEST_NOTES="${notes}" TEST_WORKFLOW_IDS_JSON="${workflow_ids_json}" RESULTS_FILE="${RESULTS_FILE}" python3 - <<'PY'
import datetime as dt
import json
import os
from pathlib import Path

workflow_ids = json.loads(os.environ.get("TEST_WORKFLOW_IDS_JSON", "[]"))
if not isinstance(workflow_ids, list):
    workflow_ids = []

row = {
  "test_name": os.environ["TEST_NAME"],
  "status": os.environ["TEST_STATUS"],
  "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
  "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
  "workflow_ids": workflow_ids,
  "notes": os.environ.get("TEST_NOTES", "")
}
path = Path(os.environ["RESULTS_FILE"])
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("a", encoding="utf-8") as f:
    f.write(json.dumps(row, ensure_ascii=True) + "\n")
PY
}

run_test() {
  local test_pattern="$1"
  local workflow_ids_json="${2:-[]}"
  echo "[TEST] ${test_pattern}"
  python3 -m unittest discover -s tests -p "${test_pattern}"
  record_result "tests/${test_pattern}" "pass" "" "${workflow_ids_json}"
}

echo "[Step 1] Phase A readiness"
python3 scripts/check_week7_phase_a_ready.py

echo "[Step 2] build + lint repair2 gap report"
python3 scripts/build_repair2_gap_report.py
python3 scripts/lint_repair2_gap_report.py

echo "[Step 3] KNOWN_LIMITATIONS coverage"
python3 scripts/check_known_limitations_coverage.py

echo "[Step 4] governance lint"
python3 scripts/lint_recovery_policy.py --path governance/recovery_policy.yaml --schema governance/recovery_policy_schema.yaml
python3 scripts/lint_degradation_policy.py --file config/audit_degradation_policy.yaml
python3 scripts/lint_failure_report.py
python3 scripts/check_traceability_completeness.py

echo "[Step 5] R-02 docker branch detection"
DOCKER_AVAILABLE=$(python3 - <<'PY'
import json
print(str(bool(json.load(open("governance/audits/repair2_gap_report.json"))["docker_available"])).lower())
PY
)
echo "[INFO] docker_available=${DOCKER_AVAILABLE}"

echo "[Step 6] P1/P2 tests + result capture"
if [ "${DOCKER_AVAILABLE}" = "true" ]; then
  run_test "test_tool_worker_l3_docker.py" '["wf-docker"]'
else
  record_result "tests/test_tool_worker_l3_docker.py" "skip" "docker unavailable"
fi
run_test "test_tool_worker_l3_guard.py"
run_test "test_lint_degradation_policy.py"
run_test "test_degraded_low_risk_unknown_scope.py"
run_test "test_fallback_chain_offline.py"
run_test "test_release_gate_metadata_quality.py"
run_test "test_lint_recovery_policy.py"
run_test "test_check_sandbox_write_boundary.py"

echo "[Step 7] lint week7 test results"
python3 scripts/lint_week7_test_results.py

echo "[Step 8] build + lint workflow registry"
python3 scripts/build_week7_workflow_registry.py
python3 scripts/lint_week7_workflow_registry.py

echo "[Step 9] build + lint acceptance summary"
python3 scripts/build_week7_acceptance_summary.py
python3 scripts/lint_week7_acceptance_summary.py

echo "[Step 10] sandbox write boundary check"
python3 scripts/check_sandbox_write_boundary.py

echo "[Step 11] Week6 regression"
./scripts/run_week6_acceptance.sh

echo "PRE_PASS" > "${AUDITS_DIR}/run_week7_pre_acceptance.status"
echo "[PASS] PRE_PASS"
