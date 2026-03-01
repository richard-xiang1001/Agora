#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import subprocess
from typing import Any

import yaml


def _load_yaml(path: pathlib.Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML object")
    return data


def _check_failure_report_draft(path: pathlib.Path) -> list[str]:
    errs: list[str] = []
    if not path.exists():
        return [f"[MISSING_011_DRAFT] file not found: {path}"]
    if path.stat().st_size == 0:
        return [f"[MISSING_011_DRAFT] file is empty: {path}"]
    try:
        data = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return [f"[MISSING_011_DRAFT] invalid yaml: {exc}"]

    required = ("failure_id", "root_cause", "next_week_action")
    for field in required:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errs.append(f"[MISSING_011_DRAFT] missing required field: {field}")

    if isinstance(data.get("failure_id"), str) and data.get("failure_id") != "AGR-011":
        errs.append("[MISSING_011_DRAFT] failure_id must be AGR-011")
    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Week7 Phase A manual prerequisites.")
    parser.add_argument("--known-limitations", default="KNOWN_LIMITATIONS.md")
    parser.add_argument("--failure-report", default="governance/failures/failure_report_011.yaml")
    args = parser.parse_args()

    # Reuse coverage checker as strict prerequisite.
    proc = subprocess.run(
        ["python3", "scripts/check_known_limitations_coverage.py", "--path", args.known_limitations],
        capture_output=True,
        text=True,
    )
    errors: list[str] = []
    if proc.returncode != 0:
        if proc.stdout.strip():
            for line in proc.stdout.strip().splitlines():
                errors.append(f"[MISSING_P3] {line}")
        if proc.stderr.strip():
            for line in proc.stderr.strip().splitlines():
                errors.append(f"[MISSING_P3] {line}")
        errors.append("[MISSING_P3] KNOWN_LIMITATIONS coverage check failed")

    errors.extend(_check_failure_report_draft(pathlib.Path(args.failure_report)))

    if errors:
        print("[FAIL] week7 phase-a readiness")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 phase-a readiness")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
