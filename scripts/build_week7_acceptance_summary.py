#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def _read_results(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Build week7 acceptance summary.")
    parser.add_argument("--context", default="governance/audits/week7_runtime_context.json")
    parser.add_argument("--gap", default="governance/audits/repair2_gap_report.json")
    parser.add_argument("--results", default="governance/audits/week7_test_results.jsonl")
    parser.add_argument("--registry", default="governance/audits/week7_workflow_registry.json")
    parser.add_argument("--out", default="governance/audits/week7_acceptance_summary.json")
    args = parser.parse_args()

    ctx = _read_json(Path(args.context))
    gap = _read_json(Path(args.gap))
    registry = _read_json(Path(args.registry))
    rows = _read_results(Path(args.results))

    tests_passed = sum(1 for r in rows if r.get("status") == "pass")
    tests_failed = sum(1 for r in rows if r.get("status") == "fail")
    downgraded: list[str] = []
    if not bool(gap.get("docker_available", False)):
        downgraded.append("R-02")

    out = {
        "run_id": str(ctx.get("run_id", "")),
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "t0": str(ctx.get("t0", "")),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "docker_available": bool(gap.get("docker_available", False)),
        "executed_workflow_ids": list(registry.get("workflow_ids", [])),
        "downgraded_risks": downgraded,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
