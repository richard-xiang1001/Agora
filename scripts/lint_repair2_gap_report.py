#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint repair2 gap report JSON.")
    parser.add_argument("--path", default="governance/audits/repair2_gap_report.json")
    parser.add_argument("--schema", default="governance/audits/repair2_gap_report_schema.json")
    args = parser.parse_args()

    report = _load_json(Path(args.path))
    schema = _load_json(Path(args.schema))

    errors: list[str] = []
    for f in schema.get("required_fields", []):
        if f not in report:
            errors.append(f"missing required field: {f}")

    checks = report.get("docker_checks")
    if not isinstance(checks, dict):
        errors.append("docker_checks must be object")
    else:
        for f in schema.get("docker_checks_required_fields", []):
            if not isinstance(checks.get(f), bool):
                errors.append(f"docker_checks.{f} must be boolean")

    if not isinstance(report.get("docker_available"), bool):
        errors.append("docker_available must be boolean")
    if not isinstance(report.get("implemented_evidence"), list):
        errors.append("implemented_evidence must be list")
    if not isinstance(report.get("gaps"), list):
        errors.append("gaps must be list")
    if not isinstance(report.get("derived_work_items"), list):
        errors.append("derived_work_items must be list")

    if errors:
        print("[FAIL] repair2 gap report lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] repair2 gap report lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
