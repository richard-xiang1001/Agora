#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agora.capability_redteam import run_capability_redteam
from agora.chat_tool_quality_dashboard import read_benchmark_json, read_history_jsonl
from agora.doctor_migration import build_doctor_report
from agora.product_path_release_gate import evaluate_product_path_release, load_product_path_thresholds
from agora.reliability_release_gate import evaluate_reliability_release_gate, load_reliability_gate_config
from agora.runtime_invariants import check_runtime_invariants


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _desktop_run_passed(payload: dict[str, Any], returncode: int = 0) -> bool:
    cleanup = payload.get("cleanup") if isinstance(payload.get("cleanup"), dict) else {}
    if cleanup and bool(cleanup.get("required", False)) and not bool(cleanup.get("passed")):
        return False
    if str(payload.get("status") or "").strip().lower() in {"passed", "pass"}:
        return returncode == 0
    return bool(payload.get("passed")) and returncode == 0


def _desktop_skip(root: Path, out: Path) -> dict[str, Any]:
    payload = {
        "schema_version": "agora_desktop_dogfood_gate_v1",
        "status": "passed",
        "passed": True,
        "mode": "skip",
        "blocked": False,
        "summary": {"required_count": 1, "required_passed": 1},
        "notes": ["desktop dogfood execution skipped by CLI; used for unit/integration gate wiring only"],
        "report_path": str(out),
    }
    _write_json(out, payload)
    return payload


def _run_desktop_api(root: Path, out: Path) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts/smoke_agent_team_desktop_validation.py"),
        "--output",
        str(out),
        "--runtime-governor-smoke",
    ]
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True, timeout=120)
    if out.exists():
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("report_path", str(out))
                payload.setdefault("status", "passed" if proc.returncode == 0 else "failed")
                payload.setdefault("passed", proc.returncode == 0)
                payload.setdefault("blocked", proc.returncode != 0)
                _write_json(out, payload)
                return payload
        except Exception:
            pass
    payload = {
        "schema_version": "agora_desktop_dogfood_gate_v1",
        "status": "passed" if proc.returncode == 0 else "failed",
        "passed": proc.returncode == 0,
        "blocked": proc.returncode != 0,
        "mode": "api",
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
        "summary": {"required_count": 1, "required_passed": 1 if proc.returncode == 0 else 0},
        "report_path": str(out),
    }
    _write_json(out, payload)
    return payload


def _run_desktop_electron_once(root: Path, out: Path) -> tuple[dict[str, Any], int]:
    cmd = [
        "node",
        str(ROOT / "scripts/desktop_electron_live_regression.js"),
        "--provider",
        "mock",
        "--agent-mode",
        "team",
        "--team-id",
        "research-implement-verify",
        "--validate-team-workspace",
        "--output",
        str(out),
        "--prompt",
        "Open the team runtime and start coordination.",
    ]
    proc = subprocess.run(cmd, cwd=str(root), text=True, timeout=180)
    payload = {}
    if out.exists():
        try:
            loaded = json.loads(out.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = dict(loaded)
        except Exception:
            payload = {}
    payload.setdefault("schema_version", "agora_desktop_dogfood_gate_v1")
    payload.setdefault("status", "passed" if proc.returncode == 0 else "failed")
    payload.setdefault("passed", proc.returncode == 0)
    payload.setdefault("blocked", proc.returncode != 0)
    payload.setdefault("mode", "electron")
    payload.setdefault("summary", {"required_count": 1, "required_passed": 1 if proc.returncode == 0 else 0})
    payload["report_path"] = str(out)
    _write_json(out, payload)
    return payload, proc.returncode


def _run_desktop_electron(root: Path, out: Path, *, repeat: int = 3) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    repeat_count = max(1, int(repeat or 1))
    for index in range(1, repeat_count + 1):
        run_out = out.with_name(f"{out.stem}_run_{index}{out.suffix}")
        payload, returncode = _run_desktop_electron_once(root, run_out)
        passed = _desktop_run_passed(payload, returncode=returncode)
        payload["run_index"] = index
        payload["passed"] = passed
        payload["blocked"] = not passed
        payload["returncode"] = returncode
        _write_json(run_out, payload)
        runs.append(payload)
    passed_runs = sum(1 for item in runs if bool(item.get("passed")))
    cleanup_passed = all(bool((item.get("cleanup") if isinstance(item.get("cleanup"), dict) else {}).get("passed")) for item in runs)
    first_failure = next((item for item in runs if not bool(item.get("passed"))), {})
    payload = {
        "schema_version": "agora_desktop_dogfood_gate_v1",
        "mode": "electron",
        "status": "passed" if passed_runs == repeat_count and cleanup_passed else "failed",
        "passed": passed_runs == repeat_count and cleanup_passed,
        "blocked": not (passed_runs == repeat_count and cleanup_passed),
        "summary": {
            "run_count": repeat_count,
            "passed_runs": passed_runs,
            "required_count": repeat_count,
            "required_passed": passed_runs,
            "cleanup_passed": cleanup_passed,
        },
        "cleanup": {
            "required": True,
            "passed": cleanup_passed,
            "run_count": repeat_count,
            "passed_runs": sum(1 for item in runs if bool((item.get("cleanup") if isinstance(item.get("cleanup"), dict) else {}).get("passed"))),
        },
        "runs": runs,
        "failure_stage": str(first_failure.get("failure_stage") or "") if first_failure else "",
        "report_path": str(out),
    }
    _write_json(out, payload)
    return payload


def _product_path(root: Path, *, run_benchmark: bool) -> dict[str, Any]:
    if run_benchmark:
        subprocess.run([sys.executable, str(ROOT / "scripts/benchmark_product_paths.py")], cwd=str(root), check=False, timeout=180)
    decision = evaluate_product_path_release(
        benchmark=read_benchmark_json(root / "governance/audits/product_path_benchmark.json"),
        history=read_history_jsonl(root / "governance/audits/product_path_benchmark_history.jsonl"),
        thresholds=load_product_path_thresholds(root / "config/product_path_release_gate.yaml"),
    )
    payload = {
        "blocked": decision.blocked,
        "notices": decision.notices,
        "summary": decision.summary,
        "thresholds_effective": decision.thresholds_effective,
        "report_path": str(root / "governance/audits/product_path_release_gate.json"),
    }
    _write_json(root / "governance/audits/product_path_release_gate.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Agora reliability release gate.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--desktop-mode", choices=["electron", "api", "skip"], default="")
    parser.add_argument("--desktop-repeat", type=int, default=0)
    parser.add_argument("--run-product-benchmark", action="store_true")
    parser.add_argument("--out", default="governance/audits/reliability_release_gate.json")
    args = parser.parse_args()

    root = Path(args.root)
    config = load_reliability_gate_config(root)
    desktop_mode = str(args.desktop_mode or (config.get("desktop") or {}).get("default_mode") or "electron").strip()
    desktop_repeat = int(args.desktop_repeat or (config.get("thresholds") or {}).get("desktop_repeat") or 1)
    if desktop_mode == "skip":
        thresholds = dict(config.get("thresholds") or {})
        thresholds["require_product_path_release_gate_pass"] = False
        config = {**config, "thresholds": thresholds}
    audits = root / "governance" / "audits"
    desktop_out = audits / "desktop_dogfood_gate.json"
    if desktop_mode == "skip":
        desktop = _desktop_skip(root, desktop_out)
    elif desktop_mode == "api":
        desktop = _run_desktop_api(root, desktop_out)
    else:
        desktop = _run_desktop_electron(root, desktop_out, repeat=desktop_repeat)

    invariants = check_runtime_invariants(app=None, root=root, mode="check", write_report=True)
    redteam = run_capability_redteam(root=root, out=audits / "capability_redteam_report.json")
    product = _product_path(root, run_benchmark=bool(args.run_product_benchmark))
    doctor = build_doctor_report(app=None, root=root, out=audits / "beta_packaging_readiness.json")
    gate = evaluate_reliability_release_gate(
        root=root,
        config=config,
        desktop_report=desktop,
        invariant_report=invariants,
        redteam_report=redteam,
        product_path_report=product,
        doctor_report=doctor,
        out=root / args.out,
    )
    print(json.dumps({"decision": gate.get("decision"), "blocked": gate.get("blocked"), "blockers": gate.get("blockers"), "report_path": gate.get("report_path")}, ensure_ascii=True))
    return 1 if bool(gate.get("blocked")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
