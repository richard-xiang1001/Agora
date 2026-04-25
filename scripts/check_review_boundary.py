#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "agora_review_boundary_report_v1"

COMMIT_A = {
    "agora/runtime_invariants.py",
    "scripts/check_runtime_invariants.py",
}
COMMIT_B = {
    "agora/release_evidence.py",
    "scripts/desktop_pack_preflight.py",
    "scripts/generate_release_evidence_manifest.py",
    "scripts/desktop_electron_live_regression.js",
    "scripts/build_release_evidence_bundle.py",
    "scripts/check_review_boundary.py",
    "package.json",
    "docs/runbooks/reliability_release.md",
    "docs/macos_release_checklist.md",
    ".github/pull_request_template.md",
    ".github/workflows/reliability-ci.yml",
}
COMMIT_C_PREFIXES = ("tests/",)
EVIDENCE_PREFIX = "governance/audits/"
EVIDENCE_SUFFIXES = (".json", ".jsonl", ".tsv")


def _git_status(root: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=10,
    )
    lines = proc.stdout.splitlines() if proc.returncode == 0 else []
    entries: list[dict[str, Any]] = []
    for line in lines:
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append({"xy": xy, "path": path, "staged": xy[0] not in {" ", "?"}, "unstaged": xy == "??" or xy[1] != " "})
    return entries


def _group(path: str) -> str:
    if path.startswith(EVIDENCE_PREFIX) and path.endswith(EVIDENCE_SUFFIXES):
        return "evidence"
    if path in COMMIT_A:
        return "commit_a"
    if path in COMMIT_B:
        return "commit_b"
    if path.startswith(COMMIT_C_PREFIXES):
        return "commit_c"
    return "other"


def build_report(*, root: Path) -> dict[str, Any]:
    root = root.resolve()
    entries = _git_status(root)
    groups: dict[str, list[str]] = {"commit_a": [], "commit_b": [], "commit_c": [], "evidence": [], "other": []}
    staged_groups: dict[str, list[str]] = {"commit_a": [], "commit_b": [], "commit_c": [], "evidence": [], "other": []}
    for entry in entries:
        path = str(entry["path"])
        group = _group(path)
        groups[group].append(path)
        if bool(entry.get("staged")):
            staged_groups[group].append(path)
    staged_evidence = bool(staged_groups["evidence"])
    staged_non_evidence = any(staged_groups[group] for group in ("commit_a", "commit_b", "commit_c", "other"))
    mixed_staged_evidence = staged_evidence and staged_non_evidence
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "groups": groups,
        "staged_groups": staged_groups,
        "evidence_files": groups["evidence"],
        "mixed_staged_evidence": mixed_staged_evidence,
        "suggested_staging": {
            "commit_a": sorted(path for path in groups["commit_a"] if path in COMMIT_A),
            "commit_b": sorted(path for path in groups["commit_b"] if path in COMMIT_B),
            "commit_c": sorted(groups["commit_c"]),
            "evidence": sorted(groups["evidence"]),
        },
        "notes": [
            "Keep governance/audits evidence out of product-code commits.",
            "Use a separate evidence commit or external artifact bundle for release evidence.",
        ],
    }


def _print_human(report: dict[str, Any]) -> None:
    print("Review boundary report")
    print(f"- mixed_staged_evidence: {str(report.get('mixed_staged_evidence')).lower()}")
    groups = report.get("groups") if isinstance(report.get("groups"), dict) else {}
    for key in ("commit_a", "commit_b", "commit_c", "evidence", "other"):
        values = list(groups.get(key) or [])
        print(f"- {key}: {len(values)}")
        for path in values[:20]:
            print(f"  - {path}")
        if len(values) > 20:
            print(f"  - ... {len(values) - 20} more")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Agora review boundary staging groups.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    parser.add_argument("--strict", action="store_true", help="Fail when staged evidence is mixed with staged product/test files.")
    args = parser.parse_args()
    report = build_report(root=Path(args.root))
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        _print_human(report)
        print(json.dumps({"mixed_staged_evidence": report.get("mixed_staged_evidence")}, ensure_ascii=True))
    if args.strict and bool(report.get("mixed_staged_evidence")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
