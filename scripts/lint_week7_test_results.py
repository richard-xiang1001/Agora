#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def _load_schema(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def _is_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint week7 test-results jsonl.")
    parser.add_argument("--path", default="governance/audits/week7_test_results.jsonl")
    parser.add_argument("--schema", default="governance/audits/week7_test_results_schema.json")
    args = parser.parse_args()

    schema = _load_schema(Path(args.schema))
    path = Path(args.path)
    if not path.exists():
        print(f"[FAIL] missing file: {path}")
        return 1

    valid_status = set(schema.get("valid_status", []))
    required = list(schema.get("required_fields", []))
    errors: list[str] = []

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        errors.append("file is empty")

    for idx, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"line {idx}: empty line not allowed")
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {idx}: invalid json: {exc}")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {idx}: must be json object")
            continue
        for f in required:
            if f not in row:
                errors.append(f"line {idx}: missing required field {f}")
        if row.get("status") not in valid_status:
            errors.append(f"line {idx}: invalid status {row.get('status')!r}")
        if not _is_iso(row.get("started_at")):
            errors.append(f"line {idx}: started_at must be ISO8601")
        if not _is_iso(row.get("finished_at")):
            errors.append(f"line {idx}: finished_at must be ISO8601")
        workflow_ids = row.get("workflow_ids")
        if not isinstance(workflow_ids, list) or not all(isinstance(x, str) for x in workflow_ids):
            errors.append(f"line {idx}: workflow_ids must be list[str]")

    if errors:
        print("[FAIL] week7 test results lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 test results lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
