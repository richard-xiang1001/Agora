#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agora.api import create_app


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(0.95 * (len(values) - 1))
    return float(values[idx])


def _build_client(root: Path) -> TestClient:
    for d in ["policy", "config", "sessions", "governance", "governance/redteam", "redteam", "audit/wal", "indexes"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "policy" / "routing_rules.yaml").write_text(
        yaml.safe_dump(
            {
                "rules": [
                    {
                        "name": "code_review",
                        "priority": 10,
                        "match": {"task_intent": "code_review"},
                        "route": "code_review_workflow",
                        "permissions_scope": "scope_code_review",
                        "fallback_chain": ["qwen/qwen3-4b:free"],
                        "debate_trigger": {"risk_level": ["high"]},
                    },
                    {
                        "name": "unknown",
                        "priority": 999,
                        "match": {"task_intent": "unknown"},
                        "route": "unknown_workflow",
                        "permissions_scope": "scope_unknown_intersection",
                        "fallback_chain": ["qwen/qwen3-4b:free"],
                        "debate_trigger": {},
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "config" / "llm_policy.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "provider": "openrouter",
                "mode": "mock",
                "model": "qwen/qwen3-4b:free",
                "timeout_seconds": 30,
                "max_retries": 1,
                "retry_on": [500, 502, 503],
                "fallback_on_error": False,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return TestClient(create_app(root))


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark runtime stability metrics.")
    parser.add_argument("--out", default="governance/audits/runtime_stability_benchmark.json")
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        client = _build_client(root)
        sid = client.post("/v1/sessions", json={"session_id": "s-bench-runtime"}).json()["session_id"]

        latencies_ms: list[float] = []
        errors = 0
        for i in range(args.samples):
            t0 = time.perf_counter()
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": f"review patch {i}",
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "low",
                        "reversibility": "reversible",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)
            if resp.status_code != 200:
                errors += 1

        cancel_latencies: list[float] = []
        for i in range(3):
            t0 = time.perf_counter()
            resp = client.post(
                f"/v1/sessions/{sid}/messages",
                json={
                    "command_text": f"review patch cancel {i}",
                    "cancel_after_round": 1,
                    "raw_features": {
                        "task_intent": "code_review",
                        "risk_level": "high",
                        "reversibility": "partial",
                        "requires_tools": False,
                        "confidence": 0.9,
                    },
                },
            )
            if resp.status_code == 200:
                cancel_latencies.append((time.perf_counter() - t0) * 1000.0)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": int(args.samples),
        "p95_latency_ms": round(_p95(latencies_ms), 3),
        "mean_latency_ms": round(float(statistics.mean(latencies_ms)) if latencies_ms else 0.0, 3),
        "error_rate": round(float(errors / max(1, args.samples)), 6),
        "cancel_latency_ms_p95": round(_p95(cancel_latencies), 3),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] runtime stability benchmark: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
