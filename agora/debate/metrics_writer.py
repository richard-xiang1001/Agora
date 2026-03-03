from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_debate_metrics(
    *,
    session: Path,
    call_rows: list[dict[str, Any]],
    round1_ms: int,
    round2_ms: int,
    round3_ms: int,
    total_ms: int,
    decision: str,
) -> None:
    status_hist = Counter()
    for row in call_rows:
        code = row.get("final_status_code")
        if code is not None:
            status_hist[str(code)] += 1
    failed = [r for r in call_rows if r.get("outcome") != "ok"]
    prompt_vals = [int(r["prompt_tokens"]) for r in call_rows if isinstance(r.get("prompt_tokens"), int)]
    completion_vals = [int(r["completion_tokens"]) for r in call_rows if isinstance(r.get("completion_tokens"), int)]
    total_vals = [int(r["total_tokens"]) for r in call_rows if isinstance(r.get("total_tokens"), int)]
    cost_vals = [float(r["estimated_cost_usd"]) for r in call_rows if isinstance(r.get("estimated_cost_usd"), (int, float))]
    cost_alert_total = int(sum(1 for r in call_rows if bool(r.get("cost_alert_exceeded"))))
    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_calls": len(call_rows),
        "success_calls": len(call_rows) - len(failed),
        "failed_calls": len(failed),
        "round1_ms": round1_ms,
        "round2_ms": round2_ms,
        "round3_ms": round3_ms,
        "total_ms": total_ms,
        "retry_total": int(sum(int(r.get("retry_count", 0)) for r in call_rows)),
        "timeout_total": int(sum(1 for r in call_rows if r.get("outcome") == "timeout")),
        "status_code_histogram": dict(status_hist),
        "decision": decision,
        "prompt_tokens": int(sum(prompt_vals)) if prompt_vals else None,
        "completion_tokens": int(sum(completion_vals)) if completion_vals else None,
        "total_tokens": int(sum(total_vals)) if total_vals else None,
        "estimated_cost_usd": round(sum(cost_vals), 8) if cost_vals else None,
        "cost_alert_exceeded_calls": cost_alert_total,
    }
    (session / "debate").mkdir(parents=True, exist_ok=True)
    (session / "debate" / "debate_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
