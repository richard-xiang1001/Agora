#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml


def _run_ok(cmd: list[str]) -> bool:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return p.returncode == 0


def _docker_checks() -> dict[str, bool]:
    cli_ok = _run_ok(["docker", "--version"])
    daemon_ok = _run_ok(["docker", "info"]) if cli_ok else False
    compose_plugin_ok = _run_ok(["docker", "compose", "version"]) if cli_ok else False
    compose_legacy_ok = _run_ok(["docker-compose", "version"]) if cli_ok else False
    return {
        "docker_cli_ok": cli_ok,
        "docker_daemon_ok": daemon_ok,
        "compose_plugin_ok": compose_plugin_ok,
        "compose_legacy_ok": compose_legacy_ok,
    }


def _load_failure_010(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("failure_report_010.yaml must be a YAML object")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Week7 repair gap report from failure_report_010.")
    parser.add_argument(
        "--failure-report",
        default="governance/failures/failure_report_010.yaml",
    )
    parser.add_argument(
        "--out",
        default="governance/audits/repair2_gap_report.json",
    )
    args = parser.parse_args()

    report_010 = _load_failure_010(Path(args.failure_report))
    checks = _docker_checks()
    docker_available = bool(
        checks["docker_cli_ok"]
        and checks["docker_daemon_ok"]
        and (checks["compose_plugin_ok"] or checks["compose_legacy_ok"])
    )

    implemented_evidence: list[str] = []
    gaps: list[str] = []
    work_items: list[str] = []

    next_action = str(report_010.get("next_week_action", "")).strip()
    if "failure-mode" in next_action or "governance/failure-mode" in next_action:
        # Minimal evidence probe: confirm endpoint exists in API code.
        api_text = Path("agora/api.py").read_text(encoding="utf-8")
        if "/v1/governance/failure-mode" in api_text:
            implemented_evidence.append("api_has_failure_mode_endpoint")
        else:
            gaps.append("missing_failure_mode_endpoint")
            work_items.append("add /v1/governance/failure-mode endpoint and health snapshot response")
    else:
        gaps.append("failure_report_010_next_week_action_not_parsed")
        work_items.append("manually review AGR-010 next_week_action mapping")

    if not docker_available:
        gaps.append("docker_unavailable_for_r02")
        work_items.append("prepare Docker CLI/daemon/compose and rerun Week7 pre-acceptance")

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_failure_id": str(report_010.get("failure_id", "AGR-010")),
        "next_week_action_raw": next_action,
        "docker_checks": checks,
        "docker_available": docker_available,
        "implemented_evidence": implemented_evidence,
        "gaps": gaps,
        "derived_work_items": work_items,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
