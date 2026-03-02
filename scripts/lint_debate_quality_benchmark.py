#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint debate quality benchmark output.")
    parser.add_argument("--path", default="governance/audits/debate_quality_benchmark.json")
    parser.add_argument("--out", default="governance/audits/debate_quality_benchmark_lint.json")
    args = parser.parse_args()

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    n_samples = int(data.get("n_samples", data.get("dataset_size", 0)) or 0)
    p_value = data.get("p_value")
    effect_size = data.get("effect_size")

    rows = data.get("rows")
    if not isinstance(rows, list) or len(rows) != n_samples:
        errors.append("rows_size_mismatch")
    if p_value is None:
        errors.append("missing_p_value")
    if effect_size is None:
        errors.append("missing_effect_size")

    if n_samples < 20:
        warnings.append("insufficient_samples_warn")
    if isinstance(p_value, (int, float)) and p_value >= 0.05:
        warnings.append("p_value_not_significant_warn")

    payload = {
        "sample_count": n_samples,
        "p_value": p_value,
        "effect_size": effect_size,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "quality_pass": len(errors) == 0,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    if errors:
        print("[FAIL] debate quality benchmark lint: " + ",".join(errors))
        return 1
    if warnings:
        print("[WARN] debate quality benchmark lint: " + ",".join(warnings))
    else:
        print("[PASS] debate quality benchmark lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
