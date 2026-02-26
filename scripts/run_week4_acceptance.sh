#!/usr/bin/env bash
set -euo pipefail

./scripts/run_week3_acceptance.sh
python3 scripts/check_replay_corpus.py
python3 -m unittest discover -s tests -p 'test_audit_daemon.py'
python3 -m unittest discover -s tests -p 'test_state_projector.py'

echo "[PASS] Week 4 acceptance checks complete"
