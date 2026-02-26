#!/usr/bin/env bash
set -euo pipefail

python3 scripts/lint_failure_report.py --schema governance/failure_report_schema.yaml
python3 scripts/check_path_matrix_minset.py --path governance/path_matrix_minset.yaml

python3 scripts/mvw_a_run.py --run-id run_001 --mode auto
python3 scripts/mvw_a_run.py --run-id run_002 --mode auto
python3 scripts/mvw_a_run.py --run-id run_003 --mode auto

echo "[PASS] Week 1 acceptance checks complete"
