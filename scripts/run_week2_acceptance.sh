#!/usr/bin/env bash
set -euo pipefail

python3 scripts/lint_failure_report.py --schema governance/failure_report_schema.yaml
python3 scripts/check_path_matrix_minset.py --path governance/path_matrix_minset.yaml
python3 scripts/validate_path_matrix_samples.py --matrix governance/path_matrix_minset.yaml --samples golden_tasks/path_matrix_minset/samples.yaml --min-samples 30
python3 scripts/check_free_model_policy.py
python3 -m unittest discover -s tests -p 'test_*.py'

echo "[PASS] Week 2 acceptance checks complete"
