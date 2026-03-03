#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FIELDS = ["p95_latency_ms", "error_rate", "cancel_latency_ms_p95", "n_samples"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint runtime stability benchmark and compare baseline.")
    parser.add_argument("--path", default="governance/audits/runtime_stability_benchmark.json")
    parser.add_argument("--baseline", default="governance/audits/week10_baseline.json")
    parser.add_argument("--out", default="governance/audits/runtime_stability_benchmark_lint.json")
    args = parser.parse_args()

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if Path(args.baseline).exists() else {}

    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_FIELDS:
        if key not in data:
            errors.append(f"missing_{key}")

    p95 = float(data.get("p95_latency_ms", 0.0))
    err = float(data.get("error_rate", 0.0))
    base_p95 = float(baseline.get("p95_latency_ms", p95 or 1.0))
    base_err = float(baseline.get("error_rate", err))

    regression = p95 > (base_p95 * 1.25) and err >= base_err
    if regression:
        errors.append("runtime_stability_regression_detected")

    payload = {
        "errors": errors,
        "warnings": warnings,
        "pass": len(errors) == 0,
        "runtime_stability_regression_detected": regression,
        "current": {
            "p95_latency_ms": p95,
            "error_rate": err,
        },
        "baseline": {
            "p95_latency_ms": base_p95,
            "error_rate": base_err,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    if errors:
        print("[FAIL] runtime stability benchmark lint: " + ",".join(errors))
        return 1
    print("[PASS] runtime stability benchmark lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
