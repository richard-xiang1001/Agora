#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-lint readiness check for failure report.")
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"[FAIL] file not found: {path}")
        return 1
    if path.stat().st_size == 0:
        print(f"[FAIL] file is empty: {path}")
        return 1

    try:
        report = _load(path)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] invalid yaml: {exc}")
        return 1

    errors: list[str] = []
    for key in ("failure_id", "root_cause", "next_week_action"):
        if not isinstance(report.get(key), str) or not report.get(key, "").strip():
            errors.append(f"missing required key: {key}")

    if errors:
        print("[FAIL] failure report readiness")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] failure report readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
