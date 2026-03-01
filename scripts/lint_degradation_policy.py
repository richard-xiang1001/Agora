#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

ON_BUDGET_EXCEEDED_ENUM = {"block_all_messages", "block_exec_chain", "readonly_mode"}


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint audit degradation policy schema/relations.")
    parser.add_argument("--file", default="config/audit_degradation_policy.yaml")
    args = parser.parse_args()

    policy = _load_yaml(Path(args.file))
    errors: list[str] = []

    required_top = [
        "version",
        "max_degraded_seconds",
        "max_degraded_requests",
        "allow_during_degraded",
        "on_budget_exceeded",
    ]
    for field in required_top:
        if field not in policy:
            errors.append(f"missing required field: {field}")

    max_seconds = policy.get("max_degraded_seconds")
    if not isinstance(max_seconds, int) or max_seconds <= 0:
        errors.append("max_degraded_seconds must be positive integer")

    max_requests = policy.get("max_degraded_requests")
    if not isinstance(max_requests, int) or max_requests <= 0:
        errors.append("max_degraded_requests must be positive integer")

    allow = policy.get("allow_during_degraded")
    if not isinstance(allow, dict):
        errors.append("allow_during_degraded must be object")
    else:
        risks = allow.get("risk_levels")
        routes = allow.get("routes")
        requires_tools = allow.get("requires_tools")
        if not isinstance(risks, list) or not risks or not all(isinstance(x, str) and x for x in risks):
            errors.append("allow_during_degraded.risk_levels must be non-empty string list")
        if not isinstance(routes, list) or not routes or not all(isinstance(x, str) and x for x in routes):
            errors.append("allow_during_degraded.routes must be non-empty string list")
        if not isinstance(requires_tools, bool):
            errors.append("allow_during_degraded.requires_tools must be boolean")

    on_budget = policy.get("on_budget_exceeded")
    if on_budget not in ON_BUDGET_EXCEEDED_ENUM:
        errors.append(
            f"on_budget_exceeded must be one of {sorted(ON_BUDGET_EXCEEDED_ENUM)}, got {on_budget!r}"
        )

    if errors:
        print("[FAIL] degradation policy lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] degradation policy lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
