#!/usr/bin/env python3
import argparse
import datetime as dt
import pathlib
import re
import sys
from typing import Any

import yaml

SPECIFIC_VERBS = {
    "add",
    "create",
    "update",
    "implement",
    "remove",
    "define",
    "write",
    "run",
    "test",
    "restrict",
    "validate",
}

VALID_TEST_CATEGORIES = {
    "hard_constraint",
    "injection",
    "injection_high",
    "injection_medium",
    "privilege",
    "memory_poisoning",
    "heartbeat_abuse",
    "fallback",
    "audit_integrity",
    "failure_storm",
    "governance",
}


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML object")
    return data


def lint_report(schema: dict[str, Any], report_path: pathlib.Path) -> list[str]:
    errs: list[str] = []
    report = load_yaml(report_path)

    for field in schema.get("required_fields", []):
        if field not in report:
            errs.append(f"missing required field: {field}")

    field_rules = schema.get("field_rules", {})
    for field, rules in field_rules.items():
        if field not in report:
            continue
        value = report[field]

        enum_values = rules.get("enum")
        if enum_values and value not in enum_values:
            errs.append(f"{field} must be one of {enum_values}, got {value!r}")

        pattern = rules.get("pattern")
        if pattern and (not isinstance(value, str) or not re.match(pattern, value)):
            errs.append(f"{field} does not match pattern {pattern}: {value!r}")

        if rules.get("format") == "date":
            try:
                dt.date.fromisoformat(str(value))
            except ValueError:
                errs.append(f"{field} must be ISO date YYYY-MM-DD, got {value!r}")

    action = str(report.get("next_week_action", "")).strip().lower()
    vague_phrases = schema.get("vague_phrases", [])
    if not action:
        errs.append("next_week_action must not be empty")
    else:
        # Block vague-only actions.
        if any(v in action for v in vague_phrases):
            if not any(v in action for v in SPECIFIC_VERBS):
                errs.append(
                    "next_week_action is vague; include a concrete operation target"
                )

    category = report.get("test_category")
    if not isinstance(category, str) or not category.strip():
        errs.append("test_category must be non-empty string")
    elif category not in VALID_TEST_CATEGORIES:
        errs.append(f"test_category must be one of {sorted(VALID_TEST_CATEGORIES)}, got {category!r}")

    if "test_category_detail" in report:
        detail = report.get("test_category_detail")
        if not isinstance(detail, str) or not detail.strip():
            errs.append("test_category_detail must be non-empty string when provided")

    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint Agora failure report YAML files.")
    parser.add_argument(
        "--schema",
        default="governance/failure_report_schema.yaml",
        help="Path to failure report schema file",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Single report file to lint. If omitted, lint all governance/failures/*.yaml",
    )
    args = parser.parse_args()

    schema_path = pathlib.Path(args.schema)
    schema = load_yaml(schema_path)

    if args.report:
        report_paths = [pathlib.Path(args.report)]
    else:
        report_paths = sorted(pathlib.Path("governance/failures").glob("*.yaml"))

    if not report_paths:
        print("No failure reports found to lint.", file=sys.stderr)
        return 1

    failed = False
    for report_path in report_paths:
        errs = lint_report(schema, report_path)
        if errs:
            failed = True
            print(f"[FAIL] {report_path}")
            for err in errs:
                print(f"  - {err}")
        else:
            print(f"[PASS] {report_path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
