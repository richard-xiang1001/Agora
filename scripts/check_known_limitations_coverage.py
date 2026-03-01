#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Any

import yaml

BEGIN_MARKER = "<!-- WEEK7_LIMITATIONS_BEGIN -->"
END_MARKER = "<!-- WEEK7_LIMITATIONS_END -->"

REQUIRED_KEYS = {
    "multi_instance_budget_externalization",  # R-08
    "paid_sota_coverage_gap",                 # R-09
    "cross_host_single_writer_risk",          # R-10
    "single_tenant_limit",                    # R-11
    "redteam_replay_gap",                     # R-06
}


def _extract_structured_payload(text: str) -> dict[str, Any]:
    if BEGIN_MARKER not in text or END_MARKER not in text:
        raise ValueError("missing WEEK7 limitation markers")
    start = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end = text.index(END_MARKER, start)
    block = text[start:end].strip()
    data = yaml.safe_load(block)
    if not isinstance(data, dict):
        raise ValueError("structured limitation block must be a YAML object")
    return data


def _parse_date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO date YYYY-MM-DD, got {value!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Week7 KNOWN_LIMITATIONS structured coverage.")
    parser.add_argument("--path", default="KNOWN_LIMITATIONS.md")
    parser.add_argument("--max-verified-age-days", type=int, default=30)
    args = parser.parse_args()

    text = Path(args.path).read_text(encoding="utf-8")
    errors: list[str] = []

    try:
        payload = _extract_structured_payload(text)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {args.path}: {exc}")
        return 1

    section = payload.get("week7_limitations")
    if not isinstance(section, dict):
        print("[FAIL] week7_limitations object missing")
        return 1

    today = dt.date.today()
    for key in sorted(REQUIRED_KEYS):
        row = section.get(key)
        if not isinstance(row, dict):
            errors.append(f"missing entry: {key}")
            continue

        for field in ("first_seen_on", "verified_on", "reviewed_by", "review_note"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{key}: missing required field {field}")

        verified_on = row.get("verified_on")
        if isinstance(verified_on, str) and verified_on.strip():
            try:
                verified_date = _parse_date(verified_on, f"{key}.verified_on")
            except ValueError as exc:
                errors.append(str(exc))
                continue

            age_days = (today - verified_date).days
            if age_days > args.max_verified_age_days:
                errors.append(
                    f"{key}: verified_on older than {args.max_verified_age_days} days ({age_days})"
                )

            # Anti-stamp rule: if verified today, require explicit human review note.
            if verified_date == today and not str(row.get("review_note", "")).strip():
                errors.append(f"{key}: verified_on is today but review_note is empty")

        first_seen_on = row.get("first_seen_on")
        if isinstance(first_seen_on, str) and first_seen_on.strip():
            try:
                _parse_date(first_seen_on, f"{key}.first_seen_on")
            except ValueError as exc:
                errors.append(str(exc))

    if errors:
        print("[FAIL] known limitations coverage")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("[PASS] known limitations coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
