#!/usr/bin/env bash
set -euo pipefail

./scripts/run_week5_acceptance.sh
python3 scripts/run_redteam_suite.py
python3 scripts/run_fault_storm_drill.py
python3 scripts/run_release_gate.py
python3 -m unittest discover -s tests -p 'test_api_audit_single_writer.py'
python3 -m unittest discover -s tests -p 'test_execution_controller.py'
python3 -m unittest discover -s tests -p 'test_irreversibility_gate.py'
python3 -m unittest discover -s tests -p 'test_heartbeat_audit.py'
python3 -m unittest discover -s tests -p 'test_redteam.py'
python3 -m unittest discover -s tests -p 'test_fault_storm.py'
python3 -m unittest discover -s tests -p 'test_release_gate.py'

echo "[PASS] Week 6 acceptance checks complete"
