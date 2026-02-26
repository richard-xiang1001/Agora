#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any

import yaml


def sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def parse_skill(path: pathlib.Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid SKILL.md payload: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate skill hash whitelist and approval policy.")
    parser.add_argument("--whitelist", default="config/skills_whitelist.json")
    parser.add_argument("--skills-dir", default="skills")
    parser.add_argument(
        "--maintainer-approved",
        action="store_true",
        help="Allow scope-change/new-skill checks to pass when explicit maintainer approval is present.",
    )
    args = parser.parse_args()

    w = json.loads(pathlib.Path(args.whitelist).read_text(encoding="utf-8"))
    entries = {e["name"]: e for e in w.get("entries", [])}

    errors: list[str] = []
    skills = sorted(pathlib.Path(args.skills_dir).glob("*/SKILL.md"))
    for skill_file in skills:
        data = parse_skill(skill_file)
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{skill_file}: missing valid name")
            continue

        scope = data.get("permissions_scope")
        if not isinstance(scope, str) or not scope.strip():
            errors.append(f"{skill_file}: missing permissions_scope")
            continue

        digest = sha256_file(skill_file)
        entry = entries.get(name)
        if entry is None:
            if args.maintainer_approved:
                continue
            errors.append(f"{name}: new skill requires maintainer approval and whitelist entry")
            continue

        old_scope = entry.get("permissions_scope")
        if old_scope != scope and not args.maintainer_approved:
            errors.append(
                f"{name}: permissions_scope changed ({old_scope} -> {scope}); maintainer approval required"
            )

        old_hash = entry.get("sha256")
        if old_hash != digest:
            errors.append(
                f"{name}: hash mismatch; update whitelist hash (scope change? {'yes' if old_scope != scope else 'no'})"
            )

    # Detect removed skills still present in whitelist.
    actual_names = {parse_skill(p).get("name") for p in skills}
    for wh_name in entries:
        if wh_name not in actual_names:
            errors.append(f"{wh_name}: present in whitelist but missing in skills directory")

    if errors:
        print("[FAIL] skill whitelist checks")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"[PASS] skill whitelist checks ({len(skills)} skills)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
