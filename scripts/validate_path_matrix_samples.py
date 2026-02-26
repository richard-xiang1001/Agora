#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys
from collections import Counter
from typing import Any

import yaml


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML object")
    return data


def coverage(values: list[dict[str, Any]], key: str) -> set[str]:
    out: set[str] = set()
    for row in values:
        val = row.get(key)
        if isinstance(val, str) and val:
            out.add(val)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate golden path matrix samples coverage.")
    parser.add_argument(
        "--matrix",
        default="governance/path_matrix_minset.yaml",
        help="Path to required branch checklist",
    )
    parser.add_argument(
        "--samples",
        default="golden_tasks/path_matrix_minset/samples.yaml",
        help="Path to sample list",
    )
    parser.add_argument("--min-samples", default=30, type=int)
    args = parser.parse_args()

    matrix = load_yaml(pathlib.Path(args.matrix)).get("required_branches", {})
    payload = load_yaml(pathlib.Path(args.samples))
    samples = payload.get("samples", [])

    if not isinstance(samples, list):
        print("[FAIL] samples must be a list")
        return 1

    errors: list[str] = []
    if len(samples) < args.min_samples:
        errors.append(f"sample size {len(samples)} < min {args.min_samples}")

    for key, sample_key in [
        ("task_type", "task_type"),
        ("risk_level", "risk_level"),
        ("reversibility", "reversibility"),
    ]:
        required = set(matrix.get(key, []))
        actual = coverage(samples, sample_key)
        missing = required - actual
        if missing:
            errors.append(f"missing {key}: {sorted(missing)}")

    required_unknown = set(matrix.get("unknown_degradation_cases", []))
    actual_unknown = coverage(samples, "unknown_trigger")
    missing_unknown = required_unknown - actual_unknown
    if missing_unknown:
        errors.append(f"missing unknown_degradation_cases: {sorted(missing_unknown)}")

    required_suspend = set(matrix.get("suspend_decision_paths", []))
    actual_suspend = coverage(samples, "suspend_trigger")
    missing_suspend = required_suspend - actual_suspend
    if missing_suspend:
        errors.append(f"missing suspend_decision_paths: {sorted(missing_suspend)}")

    required_fallback = set(matrix.get("fallback_chain_switches", []))
    map_back = {
        "primary_timeout": "orchestration_primary_timeout_switch",
        "primary_5xx": "reasoning_primary_5xx_switch",
    }
    actual_fallback_raw = coverage(samples, "fallback_trigger")
    actual_fallback = {map_back.get(v, v) for v in actual_fallback_raw}
    missing_fallback = required_fallback - actual_fallback
    if missing_fallback:
        errors.append(f"missing fallback_chain_switches: {sorted(missing_fallback)}")

    ids = [s.get("id") for s in samples if isinstance(s, dict)]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        errors.append(f"duplicate sample ids: {dup}")

    if errors:
        print("[FAIL] path matrix sample coverage")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"[PASS] path matrix sample coverage ({len(samples)} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
