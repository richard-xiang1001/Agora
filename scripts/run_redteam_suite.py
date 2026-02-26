#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import pathlib
from dataclasses import asdict

from agora.redteam import run_redteam_suite


def main() -> int:
    out_dir = pathlib.Path("governance/redteam")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = run_redteam_suite(
        suite_path="redteam/suite.yaml",
        thresholds_path="redteam/thresholds.yaml",
        routing_rules_path="policy/routing_rules.yaml",
        heartbeat_contract_path="config/heartbeat_contract.yaml",
    )

    rows = [asdict(r) for r in results]
    report_path = out_dir / "report_week6.json"
    report_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    md_lines = ["# Week 6 Red-team Report", ""]
    for r in results:
        status = "PASS" if r.passed_threshold else "FAIL"
        md_lines.append(
            f"- `{r.category}`: {status} | pass_rate={r.pass_rate:.2f} | threshold={r.threshold:.2f} | remediation={r.remediation}"
        )
    md_lines.append("")
    (out_dir / "report_week6.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"[PASS] redteam suite executed: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
