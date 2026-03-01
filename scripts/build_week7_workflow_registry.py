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


def main() -> int:
    parser = argparse.ArgumentParser(description="Build workflow registry from week7 test results.")
    parser.add_argument("--context", default="governance/audits/week7_runtime_context.json")
    parser.add_argument("--results", default="governance/audits/week7_test_results.jsonl")
    parser.add_argument("--out", default="governance/audits/week7_workflow_registry.json")
    args = parser.parse_args()

    ctx = _read_json(Path(args.context))
    workflow_ids: set[str] = set()
    results_path = Path(args.results)
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            for wf_id in row.get("workflow_ids", []):
                if isinstance(wf_id, str) and wf_id:
                    workflow_ids.add(wf_id)

    out = {
        "run_id": str(ctx.get("run_id", "")),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "workflow_ids": sorted(workflow_ids),
        "source_file": args.results,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
