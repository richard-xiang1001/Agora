#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _next_failure_id(failure_dir: Path) -> str:
    max_id = 0
    for p in failure_dir.glob("failure_report_*.yaml"):
        m = re.search(r"AGR-(\d{3})", p.read_text(encoding="utf-8"))
        if m:
            max_id = max(max_id, int(m.group(1)))
    return f"AGR-{max_id + 1:03d}"


def _write_failure_report(base: Path, trigger: str, observed: str, next_week_action: str) -> Path:
    failures = base / "governance" / "failures"
    failures.mkdir(parents=True, exist_ok=True)
    failure_id = _next_failure_id(failures)
    out = failures / f"failure_report_{failure_id.split('-')[-1]}.yaml"
    payload: dict[str, Any] = {
        "failure_id": failure_id,
        "component": "router",
        "trigger": trigger,
        "observed": observed,
        "expected": "OpenRouter endpoint reachable and free model returns minimal response",
        "root_cause": "OpenRouter live healthcheck failed",
        "next_week_action": next_week_action,
        "severity": "medium",
        "test_category": "fallback",
        "date": dt.date.today().isoformat(),
    }
    out.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
    return out


def _check_dns(host: str) -> tuple[bool, str]:
    try:
        ip = socket.gethostbyname(host)
        return True, f"dns_ok:{host}->{ip}"
    except Exception as exc:  # noqa: BLE001
        return False, f"dns_error:{exc.__class__.__name__}:{exc}"


def _check_openrouter_live(model: str) -> tuple[bool, str]:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": '{"ok":true}'},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        return True, f"live_ok:model={model}:len={len(content)}"
    except Exception as exc:  # noqa: BLE001
        return False, f"live_error:{exc.__class__.__name__}:{exc}"


def _run_live_probe(base: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "scripts/mvw_a_run.py",
        "--run-id",
        "run_live_openrouter_verify_001",
        "--mode",
        "live",
    ]
    proc = subprocess.run(cmd, cwd=base, capture_output=True, text=True)
    if proc.returncode == 0:
        return True, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "live_probe_ok"
    tail = (proc.stderr.strip() or proc.stdout.strip()).splitlines()
    msg = tail[-1] if tail else f"exit={proc.returncode}"
    return False, f"live_probe_error:{msg}"


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenRouter free-model healthcheck with optional failure report emission.")
    parser.add_argument("--model", default=os.getenv("OPENROUTER_MODEL_A", "qwen/qwen3-4b:free"))
    parser.add_argument("--host", default="openrouter.ai")
    parser.add_argument("--write-failure-report", action="store_true")
    parser.add_argument("--probe-live-run", action="store_true")
    args = parser.parse_args()

    base = Path(__file__).resolve().parents[1]

    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        msg = "missing OPENROUTER_API_KEY"
        print(f"[FAIL] {msg}")
        if args.write_failure_report:
            out = _write_failure_report(
                base,
                trigger="openrouter_healthcheck_missing_key",
                observed=msg,
                next_week_action="add OPENROUTER_API_KEY secret provisioning check in local bootstrap script",
            )
            print(f"[INFO] wrote failure report: {out}")
        return 1

    ok_dns, dns_msg = _check_dns(args.host)
    print(f"[{'PASS' if ok_dns else 'FAIL'}] {dns_msg}")
    if not ok_dns:
        if args.write_failure_report:
            out = _write_failure_report(
                base,
                trigger="openrouter_healthcheck_dns_failure",
                observed=dns_msg,
                next_week_action="add DNS resolver retry and host reachability diagnostics for openrouter.ai",
            )
            print(f"[INFO] wrote failure report: {out}")
        return 1

    ok_live, live_msg = _check_openrouter_live(args.model)
    print(f"[{'PASS' if ok_live else 'FAIL'}] {live_msg}")
    if not ok_live:
        if args.write_failure_report:
            out = _write_failure_report(
                base,
                trigger="openrouter_healthcheck_live_failure",
                observed=live_msg,
                next_week_action="add OpenRouter connectivity retry with timeout and provider failover diagnostics in mvw_a_run",
            )
            print(f"[INFO] wrote failure report: {out}")
        return 1

    if args.probe_live_run:
        ok_probe, probe_msg = _run_live_probe(base)
        print(f"[{'PASS' if ok_probe else 'FAIL'}] {probe_msg}")
        if not ok_probe:
            if args.write_failure_report:
                out = _write_failure_report(
                    base,
                    trigger="openrouter_live_probe_failure",
                    observed=probe_msg,
                    next_week_action="add live probe preflight and structured OpenRouter error classification in mvw_a_run",
                )
                print(f"[INFO] wrote failure report: {out}")
            return 1

    print("[PASS] openrouter healthcheck complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
