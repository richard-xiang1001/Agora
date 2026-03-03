#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Check KNOWN_LIMITATIONS vs runtime capabilities consistency.")
    parser.add_argument("--known", default="KNOWN_LIMITATIONS.md")
    parser.add_argument("--runtime", default="config/runtime_capabilities.yaml")
    parser.add_argument("--routes-dir", default="agora/routes")
    parser.add_argument("--runtime-dir", default="agora/runtime")
    parser.add_argument("--memory-dir", default="agora/memory")
    parser.add_argument("--initiative-dir", default="agora/initiative")
    args = parser.parse_args()

    known_text = Path(args.known).read_text(encoding="utf-8").lower()
    runtime = yaml.safe_load(Path(args.runtime).read_text(encoding="utf-8")) or {}
    if not isinstance(runtime, dict):
        print("[FAIL] runtime capabilities must be an object")
        return 1

    mode = str(runtime.get("l3_isolation_mode", "")).strip()
    errors: list[str] = []
    if not mode:
        errors.append("runtime missing l3_isolation_mode")
    if mode == "unimplemented":
        if "not implemented" not in known_text and "未实现" not in known_text:
            errors.append("KNOWN_LIMITATIONS must state L3 is not implemented")
    else:
        if "l3 container mount isolation is not implemented" in known_text:
            errors.append("KNOWN_LIMITATIONS still says L3 unimplemented while runtime is implemented")
        if mode.lower() not in known_text:
            errors.append(f"KNOWN_LIMITATIONS must mention current l3 mode: {mode}")

    routes_dir = Path(args.routes_dir)
    required_route_files = ["sessions.py", "workflows.py", "internal.py", "admin.py"]
    if not routes_dir.exists():
        errors.append(f"routes directory missing: {routes_dir}")
    else:
        for name in required_route_files:
            path = routes_dir / name
            if not path.exists():
                errors.append(f"route module missing: {path}")
            else:
                text = path.read_text(encoding="utf-8")
                if "APIRouter" not in text:
                    errors.append(f"route module does not define APIRouter usage: {path}")

    for mod_dir, must_files in [
        (Path(args.runtime_dir), ["queue_manager.py", "checkpoint_store.py", "loop_runner.py"]),
        (Path(args.memory_dir), ["layers.py", "write_policy.py", "retrieval.py"]),
        (Path(args.initiative_dir), ["policy_engine.py", "action_guard.py"]),
    ]:
        if not mod_dir.exists():
            errors.append(f"module directory missing: {mod_dir}")
            continue
        for name in must_files:
            p = mod_dir / name
            if not p.exists():
                errors.append(f"module file missing: {p}")

    if errors:
        print("[FAIL] known limitations/runtime consistency")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("[PASS] known limitations/runtime consistency")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
