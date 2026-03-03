from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from agora.controllers.schemas import (
    MemoryDecayResponse,
    MemoryIngestRequest,
    MemoryIngestResponse,
    MemoryQueryHit,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryStatsResponse,
)
from agora.memory.layers import MemoryLayerStore
from agora.memory.retrieval import query_memory


def ingest(*, root: Path, session_id: str, req: MemoryIngestRequest) -> MemoryIngestResponse:
    if not (root / "sessions" / session_id).exists():
        raise HTTPException(status_code=404, detail="session not found")
    store = MemoryLayerStore(root, session_id)
    inserted, rid = store.ingest(
        layer=req.layer,
        content=req.content,
        source=req.source,
        confidence=req.confidence,
        tags=req.tags,
    )
    return MemoryIngestResponse(session_id=session_id, inserted=inserted, record_id=rid, layer=req.layer)


def query(*, root: Path, session_id: str, req: MemoryQueryRequest) -> MemoryQueryResponse:
    if not (root / "sessions" / session_id).exists():
        raise HTTPException(status_code=404, detail="session not found")
    store = MemoryLayerStore(root, session_id)
    hits = [MemoryQueryHit(**x) for x in query_memory(query=req.query, rows=store.list_all(), top_k=req.top_k)]
    return MemoryQueryResponse(session_id=session_id, hits=hits)


def decay(*, root: Path, session_id: str) -> MemoryDecayResponse:
    if not (root / "sessions" / session_id).exists():
        raise HTTPException(status_code=404, detail="session not found")
    store = MemoryLayerStore(root, session_id)
    count = store.decay()
    return MemoryDecayResponse(session_id=session_id, decayed_count=count)


def stats(*, root: Path, session_id: str) -> MemoryStatsResponse:
    if not (root / "sessions" / session_id).exists():
        raise HTTPException(status_code=404, detail="session not found")
    store = MemoryLayerStore(root, session_id)
    data = store.stats()
    total = int(data.pop("total", 0))
    return MemoryStatsResponse(session_id=session_id, by_layer={k: int(v) for k, v in data.items()}, total=total)
