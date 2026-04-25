#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora.release_evidence import build_release_evidence_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Agora release evidence manifest.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--gate", default="governance/audits/reliability_release_gate.json")
    parser.add_argument("--out", default="governance/audits/release_evidence_manifest.json")
    args = parser.parse_args()
    root = Path(args.root)
    manifest = build_release_evidence_manifest(root=root, reliability_gate_path=root / args.gate, out=root / args.out, write=True)
    print(json.dumps({"report_path": manifest.get("report_path"), "decision": (manifest.get("reliability_gate") or {}).get("decision")}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
