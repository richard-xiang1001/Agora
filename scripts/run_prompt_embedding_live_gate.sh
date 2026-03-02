#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="$ROOT/governance/audits/prompt_embedding_live_gate.json"
HISTORY="$ROOT/governance/audits/prompt_embedding_live_gate_history.jsonl"
TMP_JSONL="$(mktemp)"
trap 'rm -f "$TMP_JSONL"' EXIT

mkdir -p "$ROOT/governance/audits"

append_result() {
  local name="$1"
  local rc="$2"
  local out_file="$3"
  local duration_ms="$4"
  python3 - "$name" "$rc" "$out_file" "$duration_ms" >> "$TMP_JSONL" <<'PY'
import json
import pathlib
import sys

name = sys.argv[1]
rc = int(sys.argv[2])
out_file = pathlib.Path(sys.argv[3])
duration_ms = int(sys.argv[4])
text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
tail = "\n".join(text.splitlines()[-30:])
auth_failed = ("auth_failed" in tail.lower()) or ("401" in tail) or ("403" in tail)
print(json.dumps({
    "name": name,
    "pass": rc == 0,
    "duration_ms": duration_ms,
    "auth_failed": bool(auth_failed),
    "stderr_tail": tail,
}, ensure_ascii=True))
PY
}

run_check() {
  local name="$1"
  shift
  local out_file
  out_file="$(mktemp)"
  local t0
  t0=$(python3 - <<'PY'
import time
print(time.time())
PY
)
  if "$@" >"$out_file" 2>&1; then
    local t1
    t1=$(python3 - <<'PY'
import time
print(time.time())
PY
)
    local duration
    duration=$(python3 - "$t0" "$t1" <<'PY'
import sys
print(int((float(sys.argv[2]) - float(sys.argv[1])) * 1000))
PY
)
    append_result "$name" 0 "$out_file" "$duration"
    rm -f "$out_file"
    return 0
  fi
  local rc=$?
  local t1
  t1=$(python3 - <<'PY'
import time
print(time.time())
PY
)
  local duration
  duration=$(python3 - "$t0" "$t1" <<'PY'
import sys
print(int((float(sys.argv[2]) - float(sys.argv[1])) * 1000))
PY
)
  append_result "$name" "$rc" "$out_file" "$duration"
  rm -f "$out_file"
  return "$rc"
}

if [[ "$DRY_RUN" == "true" ]]; then
  cat > "$TMP_JSONL" <<'EOF'
{"name":"healthcheck.live","pass":true,"duration_ms":100,"auth_failed":false,"stderr_tail":"dry-run"}
{"name":"test.debate_executor_real","pass":true,"duration_ms":120,"auth_failed":false,"stderr_tail":"dry-run"}
{"name":"cli.run_debate_live","pass":true,"duration_ms":130,"auth_failed":false,"stderr_tail":"dry-run"}
EOF
else
  OVERALL_FAIL=0
  model=$(python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('config/llm_policy.yaml')
raw = yaml.safe_load(p.read_text(encoding='utf-8')) or {}
print(raw.get('model', 'qwen/qwen3-4b:free'))
PY
)
  if ! run_check "healthcheck.live" python3 "$ROOT/scripts/openrouter_healthcheck.py" --mode live --model "$model"; then OVERALL_FAIL=1; fi
  if ! run_check "test.debate_executor_real" python3 -m unittest discover -s "$ROOT/tests" -p "test_debate_executor_real.py"; then OVERALL_FAIL=1; fi
  if ! run_check "cli.run_debate_live" python3 "$ROOT/scripts/run_debate.py" --diff "fix: remove unused import"; then OVERALL_FAIL=1; fi
fi

python3 - "$TMP_JSONL" "$REPORT" "$HISTORY" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

rows = []
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    if line.strip():
        rows.append(json.loads(line))

passed = all(x.get('pass') for x in rows)
total_ms = int(sum(int(x.get('duration_ms', 0)) for x in rows))
auth_failed_count = int(sum(1 for x in rows if x.get('auth_failed')))
now = datetime.now(timezone.utc).isoformat()
payload = {
    'generated_at': now,
    'passed': passed,
    'total_ms': total_ms,
    'auth_failed_count': auth_failed_count,
    'checks': rows,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
with pathlib.Path(sys.argv[3]).open('a', encoding='utf-8') as f:
    f.write(json.dumps(payload, ensure_ascii=True) + '\n')
print(f"[{'PASS' if passed else 'FAIL'}] prompt embedding live gate report: {sys.argv[2]}")
sys.exit(0 if passed else 1)
PY
