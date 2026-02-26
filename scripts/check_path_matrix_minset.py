#!/usr/bin/env python3
import argparse
import pathlib
import sys
from typing import Any

import yaml

EXPECTED = {
    "task_type": {"code_review", "research", "planning", "general", "unknown"},
    "risk_level": {"low", "medium", "high"},
    "reversibility": {"reversible", "partial", "irreversible"},
}


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("Path matrix file must be a YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate path_matrix_minset branch checklist.")
    parser.add_argument(
        "--path",
        default="governance/path_matrix_minset.yaml",
        help="Path to path matrix checklist",
    )
    args = parser.parse_args()

    data = load_yaml(pathlib.Path(args.path))
    rb = data.get("required_branches", {})

    errors: list[str] = []

    for key, expected in EXPECTED.items():
        actual = set(rb.get(key, []))
        missing = expected - actual
        if missing:
            errors.append(f"{key} missing: {sorted(missing)}")

    for extra_key in [
        "unknown_degradation_cases",
        "suspend_decision_paths",
        "fallback_chain_switches",
    ]:
        values = rb.get(extra_key, [])
        if not isinstance(values, list) or not values:
            errors.append(f"{extra_key} must be a non-empty list")

    if errors:
        print("[FAIL] path_matrix_minset")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] path_matrix_minset coverage checklist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
