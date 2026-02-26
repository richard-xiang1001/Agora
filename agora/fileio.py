from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path


class SessionLockManager:
    """In-process async lock manager keyed by session_id."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def _get_lock(self, session_id: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[session_id] = lock
            return lock

    @asynccontextmanager
    async def locked(self, session_id: str):
        lock = await self._get_lock(session_id)
        async with lock:
            yield


async def atomic_write(path: str | Path, content: str) -> None:
    """Write file atomically using temp file + fsync + replace."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        with tempfile.NamedTemporaryFile("w", delete=False, dir=str(p.parent), encoding="utf-8") as tf:
            tf.write(content)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_name = tf.name
        os.replace(tmp_name, p)

    await asyncio.to_thread(_write)
