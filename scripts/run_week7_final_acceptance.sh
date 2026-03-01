#!/usr/bin/env bash
set -euo pipefail

echo "[Step 1] pre artifacts ready"
python3 scripts/check_week7_pre_artifacts_ready.py

echo "[Step 2] failure_report_011 readiness"
python3 scripts/check_failure_report_ready.py --file governance/failures/failure_report_011.yaml

echo "[Step 3] failure_report_011 lint"
python3 scripts/lint_failure_report.py --report governance/failures/failure_report_011.yaml

echo "[Step 4] build + lint closure report"
python3 scripts/build_repair2_closure_report.py
python3 scripts/lint_repair2_closure_report.py

echo "[Step 5] cross artifact consistency"
python3 scripts/lint_week7_consistency.py

echo "FINAL_PASS" > governance/audits/run_week7_final_acceptance.status
echo "[PASS] FINAL_PASS"
