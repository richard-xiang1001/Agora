#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import pathlib
import re
from typing import Any

import yaml


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML object")
    return data


TRIGGER_VARIABLES_BY_SOURCE: dict[str, set[str]] = {
    "audit_health_snapshot": {
        "audit_state",
        "degraded_seconds",
        "normal_seconds",
        "degraded_request_count",
        "pending_wal_events",
        "wal_size_bytes",
        "budget_exceeded",
    },
    "audit_wal_size_bytes": {"wal_size_bytes"},
    "audit_event_count": {"code_review_blocked_rate", "hard_constraint_hit_rate"},
    "script_exit_code": {"discovery_gate_exit_code"},
    "failure_mode_endpoint": {"audit_state", "degraded_seconds"},
    "file_exists": set(),
}


def _normalize_boolean_ops(expr: str) -> str:
    normalized = re.sub(r"\bAND\b", "and", expr)
    normalized = re.sub(r"\bOR\b", "or", normalized)
    normalized = re.sub(r"\bNOT\b", "not", normalized)
    return normalized


def validate_trigger_expression(trigger: str, metric_source: str) -> list[str]:
    errors: list[str] = []
    normalized = _normalize_boolean_ops(trigger.strip())
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError:
        return ["trigger 不可解析为合法表达式"]

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    allowed = TRIGGER_VARIABLES_BY_SOURCE.get(metric_source, set())
    for var in sorted(names):
        if var not in allowed:
            errors.append(f"未知变量 {var}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint recovery policy schema and rule evaluability.")
    parser.add_argument("--path", default="governance/recovery_policy.yaml")
    parser.add_argument("--schema", default="governance/recovery_policy_schema.yaml")
    args = parser.parse_args()

    data = load_yaml(pathlib.Path(args.path))
    schema = load_yaml(pathlib.Path(args.schema))

    allowed_sources = set(schema.get("allowed_metric_sources", []))
    errors: list[str] = []
    warnings: list[str] = []

    rules = data.get("rules", [])
    if not isinstance(rules, list) or not rules:
        errors.append("rules must be a non-empty list")
        rules = []

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rule[{i}] must be object")
            continue
        rid = str(rule.get("id", f"rule[{i}]"))
        source = str(rule.get("metric_source", ""))
        trigger = str(rule.get("trigger", "")).strip()
        action = str(rule.get("action", "")).strip()
        mode = str(rule.get("auto_or_manual", "")).strip()
        window = rule.get("evaluation_window")

        if source not in allowed_sources:
            errors.append(f"{rid}: unsupported metric_source {source!r}")
        if not trigger:
            errors.append(f"{rid}: trigger required")
        else:
            for err in validate_trigger_expression(trigger, source):
                errors.append(f"{rid}: {err}")
        if not action:
            errors.append(f"{rid}: action required")
        if mode not in {"machine", "manual"}:
            errors.append(f"{rid}: auto_or_manual must be machine|manual")

        if not isinstance(window, dict):
            errors.append(f"{rid}: evaluation_window must be object")
        else:
            t = window.get("type")
            v = window.get("value")
            if t not in {"requests", "minutes", "runs", "instant"}:
                errors.append(f"{rid}: evaluation_window.type invalid: {t!r}")
            if t != "instant":
                if not isinstance(v, int) or v <= 0:
                    errors.append(f"{rid}: evaluation_window.value must be positive int")

        if mode == "manual":
            if not isinstance(rule.get("max_response_minutes"), int):
                errors.append(f"{rid}: manual rule requires max_response_minutes(int)")
            if not str(rule.get("evidence_path", "")).strip():
                errors.append(f"{rid}: manual rule requires evidence_path")
            if "escalation_to_machine_date" not in rule:
                errors.append(f"{rid}: manual rule requires escalation_to_machine_date")
            elif str(rule.get("escalation_to_machine_date")).strip().lower() == "tbd":
                warnings.append(f"{rid}: escalation_to_machine_date is tbd")

    if errors:
        print("[FAIL] recovery policy lint")
        for e in errors:
            print(f"  - {e}")
        return 1

    if warnings:
        print("[WARN] recovery policy lint")
        for w in warnings:
            print(f"  - {w}")
    print("[PASS] recovery policy lint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
