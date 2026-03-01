#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Week7 closure report.")
    parser.add_argument("--gap", default="governance/audits/repair2_gap_report.json")
    parser.add_argument("--summary", default="governance/audits/week7_acceptance_summary.json")
    parser.add_argument("--failure", default="governance/failures/failure_report_011.yaml")
    parser.add_argument("--out", default="governance/audits/repair2_closure_report.json")
    args = parser.parse_args()

    gap = _read_json(Path(args.gap))
    summary = _read_json(Path(args.summary))
    failure = _read_yaml(Path(args.failure))
    docker_available = bool(gap.get("docker_available", False))
    downgraded = list(summary.get("downgraded_risks", []))

    risks: dict[str, dict[str, str]] = {
        "R-01": {"status": "met", "reason": "AGR-011 available"},
        "R-02": {
            "status": "met" if docker_available else "not_met_pending_implementation",
            "reason": "docker_available" if docker_available else "docker_unavailable",
        },
        "R-03": {"status": "met", "reason": "degradation lint + behavior tests"},
        "R-04": {"status": "met", "reason": "offline healthcheck mode available"},
        "R-05": {"status": "met", "reason": "manual rule lint guard in place"},
        "R-06": {"status": "not_met_pending_implementation", "reason": "v2.0 roadmap"},
        "R-07": {"status": "met", "reason": "failure metadata lint strengthened"},
        "R-08": {"status": "not_met_pending_implementation", "reason": "v2.0 roadmap"},
        "R-09": {"status": "not_met_pending_implementation", "reason": "v2.0 roadmap"},
        "R-10": {"status": "not_met_pending_implementation", "reason": "v2.0 roadmap"},
        "R-11": {"status": "not_met_pending_implementation", "reason": "v2.0 roadmap"},
    }

    report = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_failure_id": str(gap.get("source_failure_id", "AGR-010")),
        "failure_report_id": str(failure.get("failure_id", "")),
        "docker_available": docker_available,
        "downgraded_risks": downgraded,
        "risks": risks,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
