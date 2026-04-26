#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora.release_evidence import build_release_evidence_manifest


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reliability preflight before packaging Agora desktop.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--desktop-mode", choices=["electron", "api", "skip"], default="")
    parser.add_argument("--desktop-repeat", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Run the release gate and evidence manifest, but do not invoke electron-builder.")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a dirty git workspace for local packaging experiments. Do not use for official releases.",
    )
    parser.add_argument("--gate-out", default="governance/audits/reliability_release_gate.json")
    parser.add_argument("--manifest-out", default="governance/audits/release_evidence_manifest.json")
    args, pack_args = parser.parse_known_args()

    root = Path(args.root)
    gate_cmd = [
        sys.executable,
        str(ROOT / "scripts/run_reliability_release_gate.py"),
        "--root",
        str(root),
        "--out",
        args.gate_out,
    ]
    if args.desktop_mode:
        gate_cmd.extend(["--desktop-mode", args.desktop_mode])
    if args.desktop_repeat:
        gate_cmd.extend(["--desktop-repeat", str(args.desktop_repeat)])
    gate_proc = subprocess.run(gate_cmd, cwd=str(root), text=True)
    gate_path = root / args.gate_out
    gate = _read_json(gate_path)
    manifest_probe = build_release_evidence_manifest(root=root, reliability_gate_path=gate_path, out=root / args.manifest_out, write=False)
    git_dirty = bool((manifest_probe.get("git") or {}).get("dirty"))
    dirty_blocked = bool(git_dirty and not args.dry_run and not args.allow_dirty)
    release_policy = {
        "official_pack_entrypoint": "desktop:pack",
        "raw_pack_entrypoint": "desktop:pack:raw",
        "raw_pack_release_allowed": False,
        "dirty_workspace": git_dirty,
        "dirty_workspace_policy": "block_official_release_allow_dry_run",
        "dry_run": bool(args.dry_run),
        "allow_dirty": bool(args.allow_dirty),
        "dirty_workspace_blocked": dirty_blocked,
        "decision": "blocked_dirty_workspace" if dirty_blocked else "allowed",
    }
    manifest = build_release_evidence_manifest(
        root=root,
        reliability_gate_path=gate_path,
        out=root / args.manifest_out,
        write=True,
        release_policy=release_policy,
    )
    if gate_proc.returncode != 0 or bool(gate.get("blocked")):
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "gate_returncode": gate_proc.returncode,
                    "gate_decision": gate.get("decision"),
                    "blockers": gate.get("blockers"),
                    "gate_report_path": str(gate_path),
                    "manifest_path": manifest.get("report_path"),
                    "release_policy": release_policy,
                },
                ensure_ascii=True,
            )
        )
        return 1
    if dirty_blocked:
        print(
            json.dumps(
                {
                    "status": "blocked_dirty_workspace",
                    "dry_run": False,
                    "gate_report_path": str(gate_path),
                    "manifest_path": manifest.get("report_path"),
                    "pack_invoked": False,
                    "release_policy": release_policy,
                },
                ensure_ascii=True,
            )
        )
        return 1
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "passed",
                    "dry_run": True,
                    "gate_report_path": str(gate_path),
                    "manifest_path": manifest.get("report_path"),
                    "pack_invoked": False,
                    "release_policy": release_policy,
                },
                ensure_ascii=True,
            )
        )
        return 0
    pack_cmd = ["npm", "run", "desktop:pack:raw", "--", *pack_args]
    pack_proc = subprocess.run(pack_cmd, cwd=str(root), text=True)
    return int(pack_proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
