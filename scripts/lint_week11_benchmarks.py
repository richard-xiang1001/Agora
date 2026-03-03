#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint Week11 benchmark artifacts.")
    parser.add_argument("--memory", default="governance/audits/memory_effectiveness_benchmark.json")
    parser.add_argument("--runtime", default="governance/audits/runtime_continuity_benchmark.json")
    parser.add_argument("--out", default="governance/audits/week11_benchmark_lint.json")
    args = parser.parse_args()

    mem = json.loads(Path(args.memory).read_text(encoding="utf-8"))
    rt = json.loads(Path(args.runtime).read_text(encoding="utf-8"))

    errors: list[str] = []
    warnings: list[str] = []

    for k in ["recall_at_k", "precision_at_k", "hit_path_distribution"]:
        if k not in mem:
            errors.append(f"memory_missing_{k}")
    for k in ["p95_recovery_latency_ms", "recovery_success_rate", "failed_recoveries"]:
        if k not in rt:
            errors.append(f"runtime_missing_{k}")

    if float(rt.get("recovery_success_rate", 0.0)) < 1.0:
        errors.append("runtime_recovery_not_full")
    if float(mem.get("recall_at_k", 0.0)) < 0.3:
        warnings.append("memory_recall_low_warn")

    payload = {
        "pass": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    if errors:
        print("[FAIL] week11 benchmark lint: " + ",".join(errors))
        return 1
    print("[PASS] week11 benchmark lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
