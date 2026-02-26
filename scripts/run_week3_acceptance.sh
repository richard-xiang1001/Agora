#!/usr/bin/env bash
set -euo pipefail

./scripts/run_week2_acceptance.sh
python3 -m unittest discover -s tests -p 'test_debate_engine.py'
python3 -m unittest discover -s tests -p 'test_verification_engine.py'
python3 -m unittest discover -s tests -p 'test_sandbox_gc.py'

echo "[PASS] Week 3 acceptance checks complete"
