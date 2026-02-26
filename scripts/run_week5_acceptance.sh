#!/usr/bin/env bash
set -euo pipefail

./scripts/run_week4_acceptance.sh
python3 scripts/check_traceability.py --path governance/traceability.yaml
python3 scripts/check_skill_whitelist.py --whitelist config/skills_whitelist.json --skills-dir skills
python3 -m unittest discover -s tests -p 'test_model_registry.py'
python3 -m unittest discover -s tests -p 'test_memory_store.py'

echo "[PASS] Week 5 acceptance checks complete"
