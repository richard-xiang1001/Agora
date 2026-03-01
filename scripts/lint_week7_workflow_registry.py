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


def _is_iso(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint week7 workflow registry.")
    parser.add_argument("--path", default="governance/audits/week7_workflow_registry.json")
    parser.add_argument("--schema", default="governance/audits/week7_workflow_registry_schema.json")
    args = parser.parse_args()

    data = _load(Path(args.path))
    schema = _load(Path(args.schema))
    errors: list[str] = []
    for f in schema.get("required_fields", []):
        if f not in data:
            errors.append(f"missing required field: {f}")

    if not isinstance(data.get("run_id"), str) or not data["run_id"].strip():
        errors.append("run_id must be non-empty string")
    if not _is_iso(data.get("generated_at")):
        errors.append("generated_at must be ISO8601")
    if not isinstance(data.get("source_file"), str) or not data["source_file"].strip():
        errors.append("source_file must be non-empty string")
    workflow_ids = data.get("workflow_ids")
    if not isinstance(workflow_ids, list) or not all(isinstance(x, str) for x in workflow_ids):
        errors.append("workflow_ids must be list[str]")

    if errors:
        print("[FAIL] week7 workflow registry lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 workflow registry lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
