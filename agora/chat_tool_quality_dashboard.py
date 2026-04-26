from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_benchmark_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_history_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _terminal_breakdown(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in dict((row.get("summary") or {}).get("live_terminal_breakdown") or {}).items():
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            counts[normalized_key] = counts.get(normalized_key, 0) + int(value or 0)
    return counts


def build_dashboard(*, benchmark: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    summary = dict(benchmark.get("summary") or {})
    cases = [dict(item) for item in list(benchmark.get("cases") or []) if isinstance(item, dict)]
    recent = history[-10:]
    live_pass_rates: list[float] = []
    for row in recent:
        row_summary = dict(row.get("summary") or {})
        executed = int(row_summary.get("live_executed") or 0)
        passed = int(row_summary.get("live_passed") or 0)
        live_pass_rates.append((passed / executed) if executed > 0 else 0.0)
    failing_cases = [
        {
            "case_id": str(item.get("case_id") or "").strip(),
            "terminal_class": str(((item.get("live_run") or {}).get("terminal_class") or "")).strip(),
            "workflow_status": str(((item.get("live_run") or {}).get("workflow_status") or "")).strip(),
            "stop_reason": str(((item.get("live_run") or {}).get("stop_reason") or "")).strip(),
        }
        for item in cases
        if not bool((item.get("live_run") or {}).get("passed"))
    ]
    return {
        "generated_at": str(benchmark.get("generated_at") or ""),
        "current": {
            "summary": summary,
            "environment": dict(benchmark.get("environment") or {}),
            "failing_cases": failing_cases,
        },
        "trend": {
            "history_samples": len(history),
            "recent_window": len(recent),
            "average_live_pass_rate": _mean(live_pass_rates),
            "live_terminal_breakdown_aggregate": _terminal_breakdown(recent),
            "recent_runs": [
                {
                    "generated_at": str(item.get("generated_at") or ""),
                    "live_passed": int(((item.get("summary") or {}).get("live_passed") or 0)),
                    "live_executed": int(((item.get("summary") or {}).get("live_executed") or 0)),
                    "live_failed": int(((item.get("summary") or {}).get("live_failed") or 0)),
                }
                for item in recent
            ],
        },
    }
