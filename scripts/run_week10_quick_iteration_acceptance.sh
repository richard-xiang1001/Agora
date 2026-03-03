#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDITS_DIR="$ROOT/governance/audits"
REPORT="$AUDITS_DIR/week10_quick_iteration_report.json"
BASELINE="$AUDITS_DIR/week10_baseline.json"
RUNTIME_BENCH="$AUDITS_DIR/runtime_stability_benchmark.json"
TMP_JSONL="$(mktemp)"
trap 'rm -f "$TMP_JSONL"' EXIT
mkdir -p "$AUDITS_DIR"

append_result() {
  local name="$1"; local rc="$2"; local detail="$3"
  python3 - "$name" "$rc" "$detail" >> "$TMP_JSONL" <<'PY'
import json,sys
print(json.dumps({"name":sys.argv[1],"pass":int(sys.argv[2])==0,"rc":int(sys.argv[2]),"detail":sys.argv[3]}, ensure_ascii=True))
PY
}

run_step() {
  local name="$1"; shift
  local rc=0; local detail="ok"
  set +e
  "$@"
  rc=$?
  set -e
  [[ $rc -ne 0 ]] && detail="failed"
  append_result "$name" "$rc" "$detail"
}

# freeze baseline from current benchmark
python3 "$ROOT/scripts/benchmark_runtime_stability.py" --out "$BASELINE" --samples 8 >/dev/null

# 1) Week10 tests
run_step "tests.week10.debate_layer" python3 -m unittest discover -s "$ROOT/tests" -p "test_debate_layer_structure.py"
run_step "tests.week10.llm_layer" python3 -m unittest discover -s "$ROOT/tests" -p "test_llm_layer_structure.py"
run_step "tests.week10.budget_policy" python3 -m unittest discover -s "$ROOT/tests" -p "test_budget_policy.py"
run_step "tests.week10.budget_policy_degraded" python3 -m unittest discover -s "$ROOT/tests" -p "test_budget_policy_degraded_execution.py"
run_step "tests.week10.runtime_stability" python3 -m unittest discover -s "$ROOT/tests" -p "test_runtime_stability_benchmark.py"

# 2) Week9 key regression
run_step "tests.week9.contract" python3 -m unittest discover -s "$ROOT/tests" -p "test_api_contract.py"
run_step "tests.week9.cancel" python3 -m unittest discover -s "$ROOT/tests" -p "test_workflow_cancel.py"
run_step "tests.week9.live_gate" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_embedding_live_gate_script.py"

# 3) prompt embedding default gate
run_step "gate.prompt_embedding" bash "$ROOT/scripts/run_prompt_embedding_gate.sh"

# 4) live gate dry-run
run_step "gate.live_dry_run" bash "$ROOT/scripts/run_prompt_embedding_live_gate.sh" --dry-run

# 5) runtime benchmark + lint
run_step "bench.runtime_stability" python3 "$ROOT/scripts/benchmark_runtime_stability.py" --out "$RUNTIME_BENCH" --samples 12
run_step "bench.runtime_stability_lint" python3 "$ROOT/scripts/lint_runtime_stability_benchmark.py" --path "$RUNTIME_BENCH" --baseline "$BASELINE"

# 6) docs consistency
run_step "lint.known_vs_runtime" python3 "$ROOT/scripts/check_known_limitations_runtime_consistency.py"

# 7) week9 regression
run_step "regression.week9" bash "$ROOT/scripts/run_week9_quick_iteration_acceptance.sh"

python3 - "$TMP_JSONL" "$REPORT" <<'PY'
import json, pathlib, sys
from datetime import datetime, timezone
rows=[]
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if line.strip(): rows.append(json.loads(line))
passed=all(x.get('pass') for x in rows)
payload={"generated_at":datetime.now(timezone.utc).isoformat(),"overall_pass":passed,"checks":rows}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
print(f"[{'PASS' if passed else 'FAIL'}] week10 quick iteration report: {sys.argv[2]}")
sys.exit(0 if passed else 1)
PY
