#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agora.memory.layers import MemoryLayerStore
from agora.memory.retrieval import query_memory


def _recall_at_k(hits: list[dict], expected_id: str) -> float:
    return 1.0 if any(str(h.get("record_id")) == expected_id for h in hits) else 0.0


def _precision_at_k(hits: list[dict], expected_id: str, k: int) -> float:
    if k <= 0:
        return 0.0
    top = hits[:k]
    if not top:
        return 0.0
    true_pos = sum(1 for h in top if str(h.get("record_id")) == expected_id)
    return true_pos / len(top)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark memory effectiveness for layered memory retrieval.")
    parser.add_argument("--out", default="governance/audits/memory_effectiveness_benchmark.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sessions" / "s-mem").mkdir(parents=True, exist_ok=True)
        store = MemoryLayerStore(root, "s-mem")
        _, rid1 = store.ingest(layer="episodic", content="fixed auth bug in login module", source="wf:1", confidence=0.9, tags=["auth"])
        store.ingest(layer="semantic", content="budget exceeded should block execution", source="wf:2", confidence=0.8, tags=["budget"])
        store.ingest(layer="procedural", content="for rollback run week10 gate first", source="wf:3", confidence=0.7, tags=["release"])

        queries = [
            ("auth bug login", rid1),
            ("execution block budget", rid1),
            ("rollback gate", rid1),
        ]

        recalls: list[float] = []
        precisions: list[float] = []
        hit_paths: dict[str, int] = {}
        rows: list[dict] = []
        for q, expected in queries:
            hits = query_memory(query=q, rows=store.list_all(), top_k=args.top_k)
            r = _recall_at_k(hits, expected)
            p = _precision_at_k(hits, expected, args.top_k)
            recalls.append(r)
            precisions.append(p)
            for h in hits:
                hp = str(h.get("hit_path", ""))
                hit_paths[hp] = hit_paths.get(hp, 0) + 1
            rows.append({"query": q, "expected_id": expected, "recall": r, "precision": p, "hits": hits})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_queries": len(rows),
        "top_k": args.top_k,
        "recall_at_k": round(sum(recalls) / max(1, len(recalls)), 6),
        "precision_at_k": round(sum(precisions) / max(1, len(precisions)), 6),
        "hit_path_distribution": hit_paths,
        "rows": rows,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    print(f"[PASS] memory effectiveness benchmark: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
