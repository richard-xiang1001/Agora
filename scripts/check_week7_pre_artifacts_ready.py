#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure Week7 pre-acceptance artifacts are ready.")
    parser.add_argument("--audits-dir", default="governance/audits")
    args = parser.parse_args()

    audits = Path(args.audits_dir)
    required = [
        audits / "repair2_gap_report.json",
        audits / "week7_test_results.jsonl",
        audits / "week7_workflow_registry.json",
        audits / "week7_acceptance_summary.json",
        audits / "run_week7_pre_acceptance.status",
    ]
    errors: list[str] = []
    for p in required:
        if not p.exists():
            errors.append(f"missing artifact: {p}")

    status_path = audits / "run_week7_pre_acceptance.status"
    if status_path.exists():
        status = status_path.read_text(encoding="utf-8").strip()
        if status != "PRE_PASS":
            errors.append(f"invalid pre status: expected PRE_PASS, got {status!r}")

    if errors:
        print("[FAIL] week7 pre artifacts not ready")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] week7 pre artifacts ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
