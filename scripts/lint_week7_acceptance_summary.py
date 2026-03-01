#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def _is_iso(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    try:
        dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint week7 acceptance summary.")
    parser.add_argument("--path", default="governance/audits/week7_acceptance_summary.json")
    parser.add_argument("--schema", default="governance/audits/week7_acceptance_summary_schema.json")
    args = parser.parse_args()

    data = _load(Path(args.path))
    schema = _load(Path(args.schema))
    errors: list[str] = []

    for f in schema.get("required_fields", []):
        if f not in data:
            errors.append(f"missing required field: {f}")

    if not isinstance(data.get("run_id"), str) or not data["run_id"].strip():
        errors.append("run_id must be non-empty string")
    if not _is_iso(data.get("timestamp")):
        errors.append("timestamp must be ISO8601")
    if not _is_iso(data.get("t0")):
        errors.append("t0 must be ISO8601")
    if not isinstance(data.get("tests_passed"), int) or data["tests_passed"] < 0:
        errors.append("tests_passed must be non-negative integer")
    if not isinstance(data.get("tests_failed"), int) or data["tests_failed"] < 0:
        errors.append("tests_failed must be non-negative integer")
    if not isinstance(data.get("docker_available"), bool):
        errors.append("docker_available must be boolean")
    if not isinstance(data.get("executed_workflow_ids"), list):
        errors.append("executed_workflow_ids must be list")
    if not isinstance(data.get("downgraded_risks"), list):
        errors.append("downgraded_risks must be list")

    if errors:
        print("[FAIL] week7 acceptance summary lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 acceptance summary lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
