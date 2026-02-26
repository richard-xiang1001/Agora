#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import pathlib

from agora.release_gate import apply_overdue_escalation, evaluate_release, load_thresholds


def main() -> int:
    redteam_path = pathlib.Path("governance/redteam/report_week6.json")
    if not redteam_path.exists():
        print("[FAIL] missing redteam report, run scripts/run_redteam_suite.py first")
        return 1

    redteam_results = json.loads(redteam_path.read_text(encoding="utf-8"))
    thresholds = load_thresholds("redteam/thresholds.yaml")
    escalated = apply_overdue_escalation(thresholds=thresholds, incidents_dir="incidents")
    decision = evaluate_release(redteam_results, escalated)

    out_dir = pathlib.Path("governance/redteam")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {
        "blocked": decision.blocked,
        "notices": decision.notices,
        "incidents_to_create": decision.incidents_to_create,
        "thresholds_effective": escalated,
    }
    out_path = out_dir / "release_gate_week6.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")

    # Soft failures generate incident stubs automatically.
    for incident in decision.incidents_to_create:
        p = pathlib.Path("incidents") / f"{incident['incident_id']}.yaml"
        if not p.exists():
            p.write_text(
                "\n".join(
                    [
                        f"incident_id: {incident['incident_id']}",
                        f"date: {incident['due_date']}",
                        "severity: medium",
                        f"test_category: {incident['test_category']}",
                        f"trigger: \"{incident['trigger']}\"",
                        "evidence: \"governance/redteam/report_week6.json\"",
                        "root_cause: \"auto-created by release gate soft-failure policy\"",
                        "affected_components: [redteam, release_gate]",
                        "proposed_amendment: \"N/A\"",
                        "status: open",
                        f"due_date: {incident['due_date']}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

    if decision.blocked:
        print(f"[FAIL] release gate blocked: {out_path}")
        return 1

    print(f"[PASS] release gate decision: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
