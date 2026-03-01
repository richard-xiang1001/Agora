#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    return data


def _parse_iso8601(value: str) -> bool:
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint week7 runtime context.")
    parser.add_argument("--path", default="governance/audits/week7_runtime_context.json")
    parser.add_argument("--schema", default="governance/audits/week7_runtime_context_schema.json")
    args = parser.parse_args()

    ctx = _load_json(Path(args.path))
    schema = _load_json(Path(args.schema))

    errors: list[str] = []
    for f in schema.get("required_fields", []):
        if f not in ctx:
            errors.append(f"missing required field: {f}")

    for f in ("t0", "started_at"):
        v = ctx.get(f)
        if not isinstance(v, str) or not _parse_iso8601(v):
            errors.append(f"{f} must be ISO8601 timestamp")
    if not isinstance(ctx.get("run_id"), str) or not ctx.get("run_id", "").strip():
        errors.append("run_id must be non-empty string")

    if errors:
        print("[FAIL] week7 runtime context lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 runtime context lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
