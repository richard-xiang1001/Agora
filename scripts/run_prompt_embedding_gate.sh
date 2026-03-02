#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="$ROOT/governance/audits/prompt_embedding_gate.json"
TMP_JSONL="$(mktemp)"
trap 'rm -f "$TMP_JSONL"' EXIT

mkdir -p "$ROOT/governance/audits"

append_result() {
  local name="$1"
  local rc="$2"
  local out_file="$3"
  python3 - "$name" "$rc" "$out_file" >> "$TMP_JSONL" <<'PY'
import json
import pathlib
import sys

name = sys.argv[1]
rc = int(sys.argv[2])
out_file = pathlib.Path(sys.argv[3])
text = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
tail = "\n".join(text.splitlines()[-20:])
print(json.dumps({"name": name, "pass": rc == 0, "stderr_tail": tail}, ensure_ascii=True))
PY
}

run_check() {
  local name="$1"
  shift
  local out_file
  out_file="$(mktemp)"
  if "$@" >"$out_file" 2>&1; then
    append_result "$name" 0 "$out_file"
    rm -f "$out_file"
    return 0
  fi
  local rc=$?
  append_result "$name" "$rc" "$out_file"
  rm -f "$out_file"
  return "$rc"
}

if [[ "$DRY_RUN" == "true" ]]; then
  cat > "$TMP_JSONL" <<'EOF'
{"name":"dry_run","pass":true,"stderr_tail":"dry-run"}
EOF
else
  OVERALL_FAIL=0
  # NOTE: live-network checks are intentionally excluded from this default gate.
  # Use scripts/run_prompt_embedding_live_gate.sh for OpenRouter-backed daily monitoring.
  if ! run_check "A0.headers" python3 "$ROOT/scripts/check_prompt_headers_consistency.py" --root "$ROOT"; then OVERALL_FAIL=1; fi
  if ! run_check "A1.catalog" python3 "$ROOT/scripts/check_prompt_catalog_consistency.py" --root "$ROOT"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_headers" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_headers_consistency.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_registry" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_registry.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_catalog_consistency" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_catalog_consistency.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_adapter" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_adapter_json_claim_v1.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.mvw_contract_guard" python3 -m unittest discover -s "$ROOT/tests" -p "test_mvw_claim_contract_guard.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.json_claim_enum_contract_guard" python3 -m unittest discover -s "$ROOT/tests" -p "test_json_claim_enum_contract_guard.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_binding" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_binding.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.prompt_registry_cache" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_registry_cache.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.binding_audit_integrity" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_binding_audit_integrity.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.strict_governance" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_strict_mode_governance.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.operator_policy_loading" python3 -m unittest discover -s "$ROOT/tests" -p "test_operator_policy_loading.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.authorization_policy" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_authorization_policy.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.authorization_runtime_enforcement" python3 -m unittest discover -s "$ROOT/tests" -p "test_prompt_authorization_runtime_enforcement.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.tool_need_mapping" python3 -m unittest discover -s "$ROOT/tests" -p "test_tool_need_requires_tools_mapping.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.subagent_executor_mock" python3 -m unittest discover -s "$ROOT/tests" -p "test_subagent_executor_mock.py"; then OVERALL_FAIL=1; fi
  if ! run_check "test.debate_executor_mock" python3 -m unittest discover -s "$ROOT/tests" -p "test_debate_executor_mock.py"; then OVERALL_FAIL=1; fi
fi

python3 - "$TMP_JSONL" "$REPORT" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

rows = []
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.strip():
        rows.append(json.loads(line))

passed = all(x.get("pass") for x in rows)
payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "passed": passed,
    "checks": rows,
}
pathlib.Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
print(f"[{'PASS' if passed else 'FAIL'}] prompt embedding gate report: {sys.argv[2]}")
sys.exit(0 if passed else 1)
PY
