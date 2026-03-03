from __future__ import annotations

from typing import Any


def _score(query: str, row: dict[str, Any]) -> float:
    q = query.lower().strip()
    content = str(row.get("content", "")).lower()
    tokens = [t for t in q.split() if t]
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in content)
    base = hits / max(1, len(tokens))
    weight = float(row.get("weight", row.get("confidence", 0.0)))
    return round(base * 0.7 + min(1.0, weight) * 0.3, 6)


def query_memory(*, query: str, rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        score = _score(query, row)
        if score <= 0:
            continue
        layer = str(row.get("layer", "semantic"))
        scored.append(
            {
                "record_id": str(row.get("record_id")),
                "layer": layer,
                "score": score,
                "content": str(row.get("content", "")),
                "hit_path": f"layer:{layer}",
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
