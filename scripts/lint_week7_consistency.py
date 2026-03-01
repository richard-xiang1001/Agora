#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-artifact consistency checks for Week7.")
    parser.add_argument("--gap", default="governance/audits/repair2_gap_report.json")
    parser.add_argument("--summary", default="governance/audits/week7_acceptance_summary.json")
    parser.add_argument("--closure", default="governance/audits/repair2_closure_report.json")
    parser.add_argument("--registry", default="governance/audits/week7_workflow_registry.json")
    args = parser.parse_args()

    gap = _load(Path(args.gap))
    summary = _load(Path(args.summary))
    closure = _load(Path(args.closure))
    registry = _load(Path(args.registry))

    errors: list[str] = []
    docker_available = bool(gap.get("docker_available", False))
    downgraded = {str(x) for x in summary.get("downgraded_risks", [])}
    r02 = closure.get("risks", {}).get("R-02", {})
    r02_status = r02.get("status")

    if not docker_available:
        if "R-02" not in downgraded:
            errors.append("docker unavailable but summary.downgraded_risks missing R-02")
        if r02_status != "not_met_pending_implementation":
            errors.append("docker unavailable but closure R-02 status is not not_met_pending_implementation")
    else:
        if "R-02" in downgraded:
            errors.append("docker available but summary marks R-02 as downgraded")
        if r02_status == "not_met_pending_implementation":
            errors.append("docker available but closure keeps R-02 unmet")

    executed = {str(x) for x in summary.get("executed_workflow_ids", [])}
    registered = {str(x) for x in registry.get("workflow_ids", [])}
    missing = executed - registered
    if missing:
        errors.append(f"executed_workflow_ids not in registry: {sorted(missing)}")

    if errors:
        print("[FAIL] week7 consistency lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 consistency lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
