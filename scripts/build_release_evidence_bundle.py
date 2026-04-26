#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SCHEMA_VERSION = "agora_release_evidence_bundle_v1"
SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9]+"),
]


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _git_text(root: Path, args: list[str]) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), text=True, capture_output=True, timeout=10)
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _as_root_path(root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def _artifact_candidates(root: Path, manifest: dict[str, Any], gate: dict[str, Any], manifest_path: Path, gate_path: Path) -> dict[str, Path]:
    candidates: dict[str, Path] = {
        "release_evidence_manifest": manifest_path,
        "reliability_release_gate": gate_path,
    }
    for source in (manifest.get("artifacts"), gate.get("artifacts")):
        if isinstance(source, dict):
            for key, value in source.items():
                path = _as_root_path(root, value)
                if path is not None:
                    candidates[str(key)] = path
    desktop_path = candidates.get("desktop_dogfood")
    if desktop_path is not None:
        for index in range(1, 10):
            run_path = desktop_path.with_name(f"{desktop_path.stem}_run_{index}{desktop_path.suffix}")
            if run_path.exists():
                candidates[f"desktop_dogfood_run_{index}"] = run_path
    for name in (
        "runtime_invariant_repair_ledger",
        "operator_policy_events",
        "product_path_benchmark_history",
    ):
        suffix = ".jsonl"
        path = root / "governance" / "audits" / f"{name}{suffix}"
        candidates[name] = path
    return candidates


def _copy_artifact(bundle_dir: Path, label: str, source: Path) -> dict[str, Any]:
    dest_dir = bundle_dir / "artifacts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    counter = 2
    while dest.exists():
        dest = dest_dir / f"{source.stem}_{counter}{source.suffix}"
        counter += 1
    shutil.copy2(source, dest)
    _redact_file(dest)
    return {"label": label, "source": str(source), "path": str(dest), "bytes": dest.stat().st_size}


def _redact_file(path: Path) -> None:
    if path.suffix.lower() not in {".json", ".jsonl", ".log", ".txt", ".tsv", ".md"}:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_OPENROUTER_KEY]", redacted)
    if redacted != text:
        path.write_text(redacted, encoding="utf-8")


def build_bundle(
    *,
    root: Path,
    out_dir: Path | None = None,
    manifest_path: Path | None = None,
    gate_path: Path | None = None,
    command_log: Path | None = None,
    make_zip: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = (manifest_path or root / "governance/audits/release_evidence_manifest.json")
    gate_path = (gate_path or root / "governance/audits/reliability_release_gate.json")
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    if not gate_path.is_absolute():
        gate_path = root / gate_path
    manifest = _read_json(manifest_path)
    gate = _read_json(gate_path)
    bundle_dir = out_dir or (root / "dist" / "release-evidence" / _now_stamp())
    if not bundle_dir.is_absolute():
        bundle_dir = root / bundle_dir
    candidates = _artifact_candidates(root, manifest, gate, manifest_path, gate_path)
    existing = {label: path for label, path in candidates.items() if path.exists()}
    missing = [{"label": label, "source": str(path)} for label, path in candidates.items() if not path.exists()]
    git_status = _git_text(root, ["status", "--short"])
    payload: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "root": str(root),
        "bundle_dir": str(bundle_dir),
        "dry_run": bool(dry_run),
        "git": {
            "head": _git_text(root, ["rev-parse", "HEAD"]),
            "dirty": bool(git_status),
            "status_short": git_status.splitlines(),
        },
        "reliability_gate": {
            "decision": gate.get("decision"),
            "blocked": bool(gate.get("blocked")),
            "artifact": str(gate_path),
        },
        "source_artifacts": {label: str(path) for label, path in candidates.items()},
        "copied_files": [],
        "missing_artifacts": missing,
        "command_log": None,
        "zip_path": None,
    }
    if dry_run:
        return payload
    bundle_dir.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for label, source in sorted(existing.items()):
        copied.append(_copy_artifact(bundle_dir, label, source))
    if command_log is not None:
        if not command_log.is_absolute():
            command_log = root / command_log
        if command_log.exists():
            dest = bundle_dir / "command_log.txt"
            shutil.copy2(command_log, dest)
            _redact_file(dest)
            payload["command_log"] = {"source": str(command_log), "path": str(dest), "missing": False}
        else:
            missing.append({"label": "command_log", "source": str(command_log)})
    if payload["command_log"] is None:
        dest = bundle_dir / "command_log_missing.txt"
        dest.write_text("No release rehearsal command log was provided for this evidence bundle.\n", encoding="utf-8")
        payload["command_log"] = {"path": str(dest), "missing": True}
    payload["copied_files"] = copied
    manifest_out = bundle_dir / "bundle_manifest.json"
    _write_json(manifest_out, payload)
    if make_zip:
        zip_path = bundle_dir.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(bundle_dir.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(bundle_dir.parent))
        payload["zip_path"] = str(zip_path)
        _write_json(manifest_out, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a release evidence bundle from Agora reliability artifacts.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--manifest", default="governance/audits/release_evidence_manifest.json")
    parser.add_argument("--gate", default="governance/audits/reliability_release_gate.json")
    parser.add_argument("--command-log", default="")
    parser.add_argument("--zip", action="store_true", help="Create a zip archive next to the evidence bundle directory.")
    parser.add_argument("--dry-run", action="store_true", help="Print the bundle plan without copying files.")
    args = parser.parse_args()
    root = Path(args.root)
    payload = build_bundle(
        root=root,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        manifest_path=Path(args.manifest),
        gate_path=Path(args.gate),
        command_log=Path(args.command_log) if args.command_log else None,
        make_zip=bool(args.zip),
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "bundle_dir": payload.get("bundle_dir"),
                "dry_run": payload.get("dry_run"),
                "copied_count": len(payload.get("copied_files") or []),
                "missing_count": len(payload.get("missing_artifacts") or []),
                "zip_path": payload.get("zip_path"),
                "gate_decision": (payload.get("reliability_gate") or {}).get("decision"),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
