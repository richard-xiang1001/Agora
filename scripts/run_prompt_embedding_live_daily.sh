#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALERT="$ROOT/governance/audits/prompt_embedding_live_alert.json"
mkdir -p "$ROOT/governance/audits"

gate_rc=0
trend_rc=0

if ! "$ROOT/scripts/run_prompt_embedding_live_gate.sh"; then
  gate_rc=$?
fi
if ! python3 "$ROOT/scripts/lint_prompt_embedding_live_gate.py"; then
  trend_rc=$?
fi

if [[ "$gate_rc" -ne 0 || "$trend_rc" -ne 0 ]]; then
  python3 - "$ALERT" "$gate_rc" "$trend_rc" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

path = pathlib.Path(sys.argv[1])
payload = {
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'alert': True,
    'gate_rc': int(sys.argv[2]),
    'trend_rc': int(sys.argv[3]),
}
path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding='utf-8')
print('[ALERT] prompt embedding live daily failure', file=sys.stderr)
PY
  exit 1
fi

echo "[PASS] prompt embedding live daily"
