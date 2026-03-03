#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDITS_DIR="$ROOT/governance/audits"
REPORT="$AUDITS_DIR/week11_quick_iteration_report.json"
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

run_step "tests.week11.runtime" python3 -m unittest discover -s "$ROOT/tests" -p "test_runtime_loop.py"
run_step "tests.week11.memory" python3 -m unittest discover -s "$ROOT/tests" -p "test_memory_v2.py"
run_step "tests.week11.initiative" python3 -m unittest discover -s "$ROOT/tests" -p "test_initiative_policy.py"
run_step "tests.week11.api_extensions" python3 -m unittest discover -s "$ROOT/tests" -p "test_week11_api_extensions.py"

run_step "bench.week11.memory" python3 "$ROOT/scripts/benchmark_memory_effectiveness.py" --out "$AUDITS_DIR/memory_effectiveness_benchmark.json"
run_step "bench.week11.runtime" python3 "$ROOT/scripts/benchmark_runtime_continuity.py" --out "$AUDITS_DIR/runtime_continuity_benchmark.json"
run_step "bench.week11.lint" python3 "$ROOT/scripts/lint_week11_benchmarks.py" --memory "$AUDITS_DIR/memory_effectiveness_benchmark.json" --runtime "$AUDITS_DIR/runtime_continuity_benchmark.json"

run_step "gate.prompt_embedding" bash "$ROOT/scripts/run_prompt_embedding_gate.sh"
run_step "gate.live_dry_run" bash "$ROOT/scripts/run_prompt_embedding_live_gate.sh" --dry-run
run_step "lint.known_vs_runtime" python3 "$ROOT/scripts/check_known_limitations_runtime_consistency.py"
run_step "regression.week10" bash "$ROOT/scripts/run_week10_quick_iteration_acceptance.sh"

python3 - "$TMP_JSONL" "$REPORT" <<'PY'
import json, pathlib, sys
from datetime import datetime, timezone
rows=[]
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if line.strip(): rows.append(json.loads(line))
passed=all(x.get('pass') for x in rows)
payload={"generated_at":datetime.now(timezone.utc).isoformat(),"overall_pass":passed,"checks":rows}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
print(f"[{'PASS' if passed else 'FAIL'}] week11 quick iteration report: {sys.argv[2]}")
sys.exit(0 if passed else 1)
PY
