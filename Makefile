.PHONY: test-mock test-live gate-week8 gate-week9 gate-week10 test-adversarial bench-quality check-budget bench-runtime

test-mock:
	python3 -m unittest discover -s tests -p 'test_*.py'

test-live:
	python3 scripts/openrouter_healthcheck.py --mode live
	python3 -m unittest discover -s tests -p 'test_debate_executor_real.py'

gate-week8:
	bash scripts/run_week8_quick_iteration_acceptance.sh

gate-week9:
	bash scripts/run_week9_quick_iteration_acceptance.sh

gate-week10:
	bash scripts/run_week10_quick_iteration_acceptance.sh

test-adversarial:
	python3 -m unittest discover -s tests -p 'test_hard_constraint_adversarial.py'

bench-quality:
	python3 scripts/benchmark_debate_quality.py --out governance/audits/debate_quality_benchmark_w9.json
	python3 scripts/lint_debate_quality_benchmark.py --path governance/audits/debate_quality_benchmark_w9.json

check-budget:
	python3 -m unittest discover -s tests -p 'test_session_budget.py'

bench-runtime:
	python3 scripts/benchmark_runtime_stability.py --out governance/audits/runtime_stability_benchmark.json --samples 12
	python3 scripts/lint_runtime_stability_benchmark.py --path governance/audits/runtime_stability_benchmark.json --baseline governance/audits/week10_baseline.json
