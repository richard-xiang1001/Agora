.PHONY: test-mock test-live gate-week8 gate-week9 test-adversarial bench-quality check-budget

test-mock:
	python3 -m unittest discover -s tests -p 'test_*.py'

test-live:
	python3 scripts/openrouter_healthcheck.py --mode live
	python3 -m unittest discover -s tests -p 'test_debate_executor_real.py'

gate-week8:
	bash scripts/run_week8_quick_iteration_acceptance.sh

gate-week9:
	bash scripts/run_week9_quick_iteration_acceptance.sh

test-adversarial:
	python3 -m unittest discover -s tests -p 'test_hard_constraint_adversarial.py'

bench-quality:
	python3 scripts/benchmark_debate_quality.py --out governance/audits/debate_quality_benchmark_w9.json
	python3 scripts/lint_debate_quality_benchmark.py --path governance/audits/debate_quality_benchmark_w9.json

check-budget:
	python3 -m unittest discover -s tests -p 'test_session_budget.py'
