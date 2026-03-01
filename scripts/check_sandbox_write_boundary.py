#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be object")
    return data


def _parse_iso(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _scan_modified_since(root: Path, since: dt.datetime) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)
        except OSError:
            continue
        if mtime >= since:
            out.append(p)
    return out


def check_boundary(
    *,
    summary_path: Path,
    registry_path: Path,
    sandbox_root: Path,
) -> tuple[bool, list[str]]:
    summary = _read_json(summary_path)
    registry = _read_json(registry_path)

    t0 = _parse_iso(str(summary.get("t0", "")))
    executed = {str(x) for x in summary.get("executed_workflow_ids", []) if str(x)}
    registered = {str(x) for x in registry.get("workflow_ids", []) if str(x)}
    target_ids = executed & registered
    if not target_ids:
        return True, []

    allowed_prefixes = [str((sandbox_root / wf).resolve()) + os.sep for wf in sorted(target_ids)]
    violations: list[str] = []
    for p in _scan_modified_since(sandbox_root, t0):
        resolved = str(p.resolve())
        if not any(resolved.startswith(prefix) for prefix in allowed_prefixes):
            violations.append(resolved)
    return len(violations) == 0, violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Check sandbox write boundary for Week7 run.")
    parser.add_argument("--summary", default="governance/audits/week7_acceptance_summary.json")
    parser.add_argument("--registry", default="governance/audits/week7_workflow_registry.json")
    parser.add_argument("--sandbox-root", default="/tmp/agora-sandbox")
    args = parser.parse_args()

    ok, violations = check_boundary(
        summary_path=Path(args.summary),
        registry_path=Path(args.registry),
        sandbox_root=Path(args.sandbox_root),
    )
    if not ok:
        print("[FAIL] sandbox write boundary violated")
        for v in violations:
            print(f"  - {v}")
        return 1

    print("[PASS] sandbox write boundary check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
