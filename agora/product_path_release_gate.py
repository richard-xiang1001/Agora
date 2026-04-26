from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ProductPathReleaseDecision:
    blocked: bool
    notices: list[str]
    summary: dict[str, Any]
    thresholds_effective: dict[str, Any]


def load_product_path_thresholds(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    payload = raw if isinstance(raw, dict) else {}
    thresholds = payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
    required_paths = [str(item).strip() for item in list(thresholds.get("required_passed_paths") or []) if str(item).strip()]
    return {
        "recent_window": max(1, int(thresholds.get("recent_window") or 5)),
        "min_history_samples": max(1, int(thresholds.get("min_history_samples") or 3)),
        "min_current_pass_rate": float(thresholds.get("min_current_pass_rate") or 1.0),
        "min_recent_average_pass_rate": float(thresholds.get("min_recent_average_pass_rate") or 0.95),
        "required_passed_paths": required_paths,
    }


def _pass_rate(summary: dict[str, Any]) -> float:
    executed = int(summary.get("executed") or 0)
    if executed <= 0:
        return 0.0
    return float(summary.get("passed") or 0) / executed


def _coerce_history(history: list[dict[str, Any]], benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [dict(item) for item in history if isinstance(item, dict)]
    generated_at = str(benchmark.get("generated_at") or "").strip()
    if generated_at and not any(str(item.get("generated_at") or "").strip() == generated_at for item in rows):
        rows.append({"generated_at": generated_at, "summary": dict(benchmark.get("summary") or {})})
    return rows


def evaluate_product_path_release(
    *,
    benchmark: dict[str, Any],
    history: list[dict[str, Any]],
    thresholds: dict[str, Any],
) -> ProductPathReleaseDecision:
    current_summary = dict(benchmark.get("summary") or {})
    current_cases = [dict(item) for item in list(benchmark.get("cases") or []) if isinstance(item, dict)]
    history_rows = _coerce_history(history, benchmark)
    recent_window = max(1, int(thresholds.get("recent_window") or 5))
    recent_rows = history_rows[-recent_window:]
    notices: list[str] = []
    blocked = False

    current_pass_rate = round(_pass_rate(current_summary), 3)
    recent_pass_rates = [_pass_rate(dict(item.get("summary") or {})) for item in recent_rows]
    recent_average = round(sum(recent_pass_rates) / len(recent_pass_rates), 3) if recent_pass_rates else 0.0
    min_history_samples = max(1, int(thresholds.get("min_history_samples") or 3))
    min_current = float(thresholds.get("min_current_pass_rate") or 1.0)
    min_recent = float(thresholds.get("min_recent_average_pass_rate") or 0.95)
    required_paths = [str(item).strip() for item in list(thresholds.get("required_passed_paths") or []) if str(item).strip()]

    if current_pass_rate < min_current:
        blocked = True
        notices.append(f"current_pass_rate {current_pass_rate:.3f} < {min_current:.3f}")
    if len(recent_rows) < min_history_samples:
        blocked = True
        notices.append(f"history_samples {len(recent_rows)} < {min_history_samples}")
    if recent_average < min_recent:
        blocked = True
        notices.append(f"recent_average_pass_rate {recent_average:.3f} < {min_recent:.3f}")

    passed_paths = {
        str(item.get("case_id") or "").strip()
        for item in current_cases
        if bool(item.get("passed")) and bool(item.get("artifact_assertions"))
    }
    missing_required_paths = sorted(path_id for path_id in required_paths if path_id not in passed_paths)
    if missing_required_paths:
        blocked = True
        notices.append(f"required_paths_failed: {', '.join(missing_required_paths)}")

    return ProductPathReleaseDecision(
        blocked=blocked,
        notices=notices,
        summary={
            "current_pass_rate": current_pass_rate,
            "recent_average_pass_rate": recent_average,
            "history_samples": len(recent_rows),
            "recent_window": recent_window,
            "required_paths_total": len(required_paths),
            "required_paths_passed": len(required_paths) - len(missing_required_paths),
            "missing_required_paths": missing_required_paths,
        },
        thresholds_effective={
            "recent_window": recent_window,
            "min_history_samples": min_history_samples,
            "min_current_pass_rate": min_current,
            "min_recent_average_pass_rate": min_recent,
            "required_passed_paths": required_paths,
        },
    )
