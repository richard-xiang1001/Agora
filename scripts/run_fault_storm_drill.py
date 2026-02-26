#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
import pathlib

from agora.fault_storm import run_fault_storm_drill


def main() -> int:
    out_dir = pathlib.Path("governance/redteam")
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_fault_storm_drill()
    out = {
        "timeout_failover_ok": result.timeout_failover_ok,
        "wal_readonly_ok": result.wal_readonly_ok,
        "overall_pass": result.overall_pass,
    }
    path = out_dir / "fault_storm_week6.json"
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    if not result.overall_pass:
        print(f"[FAIL] fault storm drill failed: {path}")
        return 1

    print(f"[PASS] fault storm drill: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
