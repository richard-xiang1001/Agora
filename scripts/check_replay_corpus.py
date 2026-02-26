#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

import yaml


def load_samples(path: pathlib.Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("replay corpus must be a YAML object")
    samples = payload.get("samples", [])
    if not isinstance(samples, list):
        raise ValueError("samples must be a list")
    out: list[dict[str, Any]] = []
    for item in samples:
        if isinstance(item, dict):
            out.append(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate replay corpus gate (>=200 samples).")
    parser.add_argument(
        "--path",
        default="golden_tasks/replay_corpus/samples.yaml",
        help="Replay corpus YAML path",
    )
    parser.add_argument("--min-samples", type=int, default=200)
    args = parser.parse_args()

    path = pathlib.Path(args.path)
    if not path.exists():
        print(f"[FAIL] replay corpus file not found: {path}")
        return 1

    try:
        samples = load_samples(path)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] invalid replay corpus: {exc}")
        return 1

    required = {"id", "source", "target_branch", "expected_route", "expected_status", "created_at"}
    errors: list[str] = []
    if len(samples) < args.min_samples:
        errors.append(f"sample count {len(samples)} < min {args.min_samples}")

    for i, row in enumerate(samples):
        missing = sorted(required - set(row.keys()))
        if missing:
            errors.append(f"sample[{i}] missing fields: {missing}")
            if len(errors) > 20:
                break

    if errors:
        print("[FAIL] replay corpus checks")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"[PASS] replay corpus checks ({len(samples)} samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
