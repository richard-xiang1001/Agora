#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDITS_DIR="$ROOT/governance/audits"
REPORT="$AUDITS_DIR/week9_quick_iteration_report.json"
TMP_JSONL="$(mktemp)"
trap 'rm -f "$TMP_JSONL"' EXIT
mkdir -p "$AUDITS_DIR"

append_result() {
  local name="$1"
  local rc="$2"
  local detail="$3"
  python3 - "$name" "$rc" "$detail" >> "$TMP_JSONL" <<'PY'
import json
import sys
print(json.dumps({
    "name": sys.argv[1],
    "pass": int(sys.argv[2]) == 0,
    "rc": int(sys.argv[2]),
    "detail": sys.argv[3],
}, ensure_ascii=True))
PY
}

run_step() {
  local name="$1"
  shift
  local rc=0
  local detail="ok"
  set +e
  "$@"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    detail="failed"
  fi
  append_result "$name" "$rc" "$detail"
}

# 1) Week9新增测试集合
run_step "tests.week9.api_layer_structure" python3 -m unittest discover -s "$ROOT/tests" -p "test_api_layer_structure.py"
run_step "tests.week9.hard_constraint_adversarial" python3 -m unittest discover -s "$ROOT/tests" -p "test_hard_constraint_adversarial.py"
run_step "tests.week9.session_budget" python3 -m unittest discover -s "$ROOT/tests" -p "test_session_budget.py"
run_step "tests.week9.session_rate_limit" python3 -m unittest discover -s "$ROOT/tests" -p "test_session_rate_limit.py"
run_step "tests.week9.audit_scrub" python3 -m unittest discover -s "$ROOT/tests" -p "test_audit_scrub.py"
run_step "tests.week9.cancel_after_round" python3 -m unittest discover -s "$ROOT/tests" -p "test_cancel_after_round.py"
run_step "tests.week9.debate_quality_statistics" python3 -m unittest discover -s "$ROOT/tests" -p "test_debate_quality_statistics.py"

# 2) 对抗测试集（覆盖率阈值在测试中校验）
run_step "tests.week9.adversarial_lint" python3 -m unittest discover -s "$ROOT/tests" -p "test_hard_constraint_adversarial.py"

# 3) prompt embedding default gate
run_step "gate.prompt_embedding" bash "$ROOT/scripts/run_prompt_embedding_gate.sh"

# 4) live gate（CI默认 dry-run）
run_step "gate.live_dry_run" bash "$ROOT/scripts/run_prompt_embedding_live_gate.sh" --dry-run

# 5) debate quality benchmark + 统计 lint
run_step "bench.quality" python3 "$ROOT/scripts/benchmark_debate_quality.py" --out "$ROOT/governance/audits/debate_quality_benchmark_w9.json"
run_step "bench.quality_lint" python3 "$ROOT/scripts/lint_debate_quality_benchmark.py" --path "$ROOT/governance/audits/debate_quality_benchmark_w9.json"

# 6) 文档一致性检查（含 routes 目录）
run_step "lint.known_vs_runtime" python3 "$ROOT/scripts/check_known_limitations_runtime_consistency.py"

# 7) Week8 回归
run_step "regression.week8" bash "$ROOT/scripts/run_week8_quick_iteration_acceptance.sh"

python3 - "$TMP_JSONL" "$REPORT" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone
rows = []
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if line.strip():
        rows.append(json.loads(line))
passed = all(x.get("pass") for x in rows)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "overall_pass": passed,
    "checks": rows,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
print(f"[{'PASS' if passed else 'FAIL'}] week9 quick iteration report: {sys.argv[2]}")
sys.exit(0 if passed else 1)
PY
