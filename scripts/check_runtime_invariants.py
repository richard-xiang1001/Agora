#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora.runtime_invariants import check_runtime_invariants


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Agora runtime invariants.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--mode", choices=["check", "repair-safe", "mark-legacy-safe"], default="check")
    parser.add_argument("--dry-run", action="store_true", help="For mark-legacy-safe, report planned mutations without writing workflow state. This is the default.")
    parser.add_argument("--write", action="store_true", help="For mark-legacy-safe, write eligible legacy markers and repair ledger entries.")
    parser.add_argument("--force", action="store_true", help="For mark-legacy-safe --write, refresh already-marked legacy actions and write a new ledger entry.")
    parser.add_argument("--out", default="governance/audits/runtime_invariant_report.json")
    args = parser.parse_args()
    root = Path(args.root)
    payload = check_runtime_invariants(
        app=None,
        root=root,
        mode=args.mode,
        write_report=True,
        legacy_write=bool(args.write),
        legacy_force=bool(args.force),
    )
    out = root / args.out
    if str(payload.get("report_path") or "") != str(out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    print(
        json.dumps(
            {
                "blocked": payload.get("blocked"),
                "summary": payload.get("summary"),
                "legacy_migration": payload.get("legacy_migration"),
                "planned_legacy_mutations": payload.get("planned_legacy_mutations"),
                "report_path": str(out),
            },
            ensure_ascii=True,
        )
    )
    return 1 if bool(payload.get("blocked")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
