#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import yaml

ALLOWED_STATUS = {"met", "not_met_pending_implementation"}


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("traceability file must be a YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate constitution/threshold version alignment.")
    parser.add_argument("--path", default="governance/traceability.yaml")
    args = parser.parse_args()

    data = load_yaml(pathlib.Path(args.path))
    top_const = data.get("constitution_version")
    top_test = data.get("test_threshold_version")
    entries = data.get("entries", [])
    root = pathlib.Path(".").resolve()

    errors: list[str] = []
    warnings: list[str] = []
    if not top_const or not top_test:
        errors.append("top-level constitution_version and test_threshold_version are required")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry[{i}] must be object")
            continue

        clause = entry.get("clause_id", f"entry[{i}]")
        behavioral = bool(entry.get("behavioral", False))
        status = entry.get("status")
        note = str(entry.get("coverage_note", "")).strip()
        if not note:
            errors.append(f"{clause}: coverage_note is required")

        if status is None:
            warnings.append(f"{clause}: status missing (expected one of {sorted(ALLOWED_STATUS)})")
        elif status not in ALLOWED_STATUS:
            errors.append(f"{clause}: status invalid: {status!r} (allowed: {sorted(ALLOWED_STATUS)})")

        modules = entry.get("modules")
        tests = entry.get("tests")
        if not isinstance(modules, list) or not modules:
            errors.append(f"{clause}: modules must be a non-empty list")
        if not isinstance(tests, list) or not tests:
            errors.append(f"{clause}: tests must be a non-empty list")

        for rel in modules or []:
            p = (root / str(rel)).resolve()
            if root not in p.parents and p != root:
                errors.append(f"{clause}: module path escapes repo: {rel}")
                continue
            if not p.exists():
                errors.append(f"{clause}: module path not found: {rel}")

        for rel in tests or []:
            p = (root / str(rel)).resolve()
            if root not in p.parents and p != root:
                errors.append(f"{clause}: test path escapes repo: {rel}")
                continue
            if not p.exists():
                errors.append(f"{clause}: test path not found: {rel}")

        cver = entry.get("constitution_version", top_const)
        tver = entry.get("test_threshold_version", top_test)
        if behavioral and cver != tver:
            errors.append(
                f"{clause}: behavioral=true requires constitution_version == test_threshold_version ({cver} != {tver})"
            )
        if status == "met":
            if not isinstance(tests, list) or not tests:
                warnings.append(f"{clause}: status=met but tests list is empty")

    if errors:
        print("[FAIL] traceability checks")
        for e in errors:
            print(f"  - {e}")
        return 1

    if warnings:
        print("[WARN] traceability checks")
        for w in warnings:
            print(f"  - {w}")
    print("[PASS] traceability checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
