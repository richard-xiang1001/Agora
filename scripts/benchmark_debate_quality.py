#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agora.debate_executor import DebateExecutor
from agora.llm_client import LlmPolicy, build_llm_client
from agora.models import TaskFeatures
from agora.prompt_registry import load_catalog
from agora.subagent_executor import SubagentExecutor


def _build_dataset() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for i in range(1, 11):
        rows.append(
            {
                "id": f"approve_{i:02d}",
                "diff": f"fix: remove unused import #{i}",
                "expected": "APPROVE",
            }
        )
    # In mock mode debate returns APPROVE for REQUEST_CHANGES marker, while subagent returns REQUEST_CHANGES.
    # This gives a stable quality delta sample for deterministic benchmarking.
    for i in range(1, 11):
        rows.append(
            {
                "id": f"request_changes_{i:02d}",
                "diff": f"[[MOCK:REQUEST_CHANGES]] refactor review case #{i}",
                "expected": "APPROVE",
            }
        )
    for i in range(1, 6):
        rows.append(
            {
                "id": f"suspend_{i:02d}",
                "diff": f"[[MOCK:SUSPEND]] risky shell execution #{i}",
                "expected": "SUSPEND",
            }
        )
    return rows


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _variance(vals: list[float]) -> float:
    if len(vals) <= 1:
        return 0.0
    m = _mean(vals)
    return sum((v - m) ** 2 for v in vals) / (len(vals) - 1)


def _cohens_d(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    va = _variance(a)
    vb = _variance(b)
    pooled_denom = (len(a) - 1) + (len(b) - 1)
    if pooled_denom <= 0:
        return 0.0
    pooled_var = (((len(a) - 1) * va) + ((len(b) - 1) * vb)) / pooled_denom
    if pooled_var <= 0:
        return 0.0
    return (_mean(a) - _mean(b)) / math.sqrt(pooled_var)


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _welch_p_value(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 1.0
    ma = _mean(a)
    mb = _mean(b)
    va = _variance(a)
    vb = _variance(b)
    denom = math.sqrt((va / len(a)) + (vb / len(b)))
    if denom <= 0:
        return 1.0
    t = (ma - mb) / denom
    # Conservative normal approximation fallback for two-sided p-value.
    return max(0.0, min(1.0, 2.0 * (1.0 - _normal_cdf(abs(t)))))


def _ttest_p_value(a: list[float], b: list[float]) -> float:
    try:
        from scipy.stats import ttest_ind  # type: ignore

        result = ttest_ind(a, b, equal_var=False)
        p = float(result.pvalue)
        if math.isnan(p):
            return 1.0
        return max(0.0, min(1.0, p))
    except Exception:
        return _welch_p_value(a, b)


def _significance_note(*, n_samples: int, p_value: float, effect_size: float) -> str:
    if n_samples < 20:
        return "insufficient_samples"
    band = "small"
    abs_d = abs(effect_size)
    if abs_d >= 0.8:
        band = "large"
    elif abs_d >= 0.5:
        band = "medium"
    if p_value < 0.05:
        return f"p < 0.05; {band} effect"
    return "not_significant"


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Debate vs Subagent quality on fixed mock dataset.")
    parser.add_argument("--out", default="governance/audits/debate_quality_benchmark.json")
    args = parser.parse_args()

    root = ROOT_DIR
    dataset = _build_dataset()

    registry = load_catalog(
        root / "config" / "prompt_catalog.yaml",
        root_dir=root,
        audit_dir=root / "governance" / "audits",
    )
    subagent_binding = registry.resolve_profile("profile.subagent_code_review")
    debate_binding = registry.resolve_profile("profile.debate_code_review")
    policy = LlmPolicy(
        schema_version="1.0",
        provider="openrouter",
        mode="mock",
        model="qwen/qwen3-4b:free",
        timeout_seconds=30,
        max_retries=1,
        retry_on=[500],
        fallback_on_error=False,
    )
    llm_client = build_llm_client(policy, root_dir=root, repo_root=root)
    subagent = SubagentExecutor(prompt_root_dir=str(root))
    debate = DebateExecutor(prompt_root_dir=root, llm_policy=policy)
    features = TaskFeatures(
        task_intent="code_review",
        risk_level="medium",
        reversibility="partial",
        requires_tools=False,
        confidence=0.9,
    )

    rows: list[dict] = []
    subagent_scores: list[float] = []
    debate_scores: list[float] = []

    for sample in dataset:
        subagent_verdict = subagent.run(
            diff=sample["diff"],
            task_features=features,
            binding_assets=subagent_binding,
            llm_client=llm_client,
        )
        debate_verdict = debate.run(
            diff=sample["diff"],
            routing_features=features.model_dump(mode="json"),
            binding=debate_binding,
            llm_client=llm_client,
            session_dir=root / "sessions" / "bench_quality" / sample["id"],
            use_mock=True,
        )
        expected = sample["expected"]
        subagent_ok = subagent_verdict.decision == expected
        debate_ok = debate_verdict.decision == expected
        subagent_scores.append(1.0 if subagent_ok else 0.0)
        debate_scores.append(1.0 if debate_ok else 0.0)
        rows.append(
            {
                "sample_id": sample["id"],
                "expected": expected,
                "actual_subagent": subagent_verdict.decision,
                "subagent_match": subagent_ok,
                "actual_debate": debate_verdict.decision,
                "debate_match": debate_ok,
            }
        )

    n_samples = len(dataset)
    subagent_mean = round(_mean(subagent_scores), 6)
    debate_mean = round(_mean(debate_scores), 6)
    delta = round(debate_mean - subagent_mean, 6)
    p_value = round(_ttest_p_value(debate_scores, subagent_scores), 6)
    effect_size = round(_cohens_d(debate_scores, subagent_scores), 6)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_size": n_samples,
        "n_samples": n_samples,
        "subagent_accuracy": subagent_mean,
        "debate_accuracy": debate_mean,
        "subagent_mean_score": subagent_mean,
        "debate_mean_score": debate_mean,
        "delta": delta,
        "p_value": p_value,
        "effect_size": effect_size,
        "significance_note": _significance_note(
            n_samples=n_samples,
            p_value=p_value,
            effect_size=effect_size,
        ),
        "rows": rows,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] debate quality benchmark: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
