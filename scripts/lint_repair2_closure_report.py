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
    parser = argparse.ArgumentParser(description="Lint Week7 closure report.")
    parser.add_argument("--path", default="governance/audits/repair2_closure_report.json")
    parser.add_argument("--schema", default="governance/audits/repair2_closure_report_schema.json")
    args = parser.parse_args()

    report = _load(Path(args.path))
    schema = _load(Path(args.schema))
    errors: list[str] = []

    for f in schema.get("required_fields", []):
        if f not in report:
            errors.append(f"missing required field: {f}")

    allowed_status = set(schema.get("allowed_status", []))
    risks = report.get("risks")
    if not isinstance(risks, dict):
        errors.append("risks must be object")
    else:
        for risk_id in schema.get("required_risk_ids", []):
            row = risks.get(risk_id)
            if not isinstance(row, dict):
                errors.append(f"risks.{risk_id} missing")
                continue
            status = row.get("status")
            if status not in allowed_status:
                errors.append(f"risks.{risk_id}.status invalid: {status!r}")

    if errors:
        print("[FAIL] repair2 closure report lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] repair2 closure report lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
