from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiofiles  # type: ignore[import-untyped]
import orjson


class LocalJsonBlobStore:
    """Write JSON to `root / relative_path` using orjson + aiofiles."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._locks: dict[str, asyncio.Lock] = {}

    def _abs(self, relative_path: str) -> Path:
        rel = Path(relative_path)
        if rel.is_absolute():
            msg = "relative_path must be relative"
            raise ValueError(msg)
        return (self.root / rel).resolve()

    def _lock_for(self, relative_path: str) -> asyncio.Lock:
        lock = self._locks.get(relative_path)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[relative_path] = lock
        return lock

    async def write_json(self, relative_path: str, payload: Any) -> None:
        async with self._lock_for(relative_path):
            path = self._abs(relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = orjson.dumps(payload, option=orjson.OPT_INDENT_2)
            tmp = path.with_suffix(path.suffix + ".tmp")
            async with aiofiles.open(tmp, "wb") as f:
                await f.write(data)
            tmp.replace(path)

    async def read_json(self, relative_path: str) -> Any | None:
        path = self._abs(relative_path)
        if not path.exists():
            return None
        async with aiofiles.open(path, "rb") as f:
            raw = await f.read()
        return orjson.loads(raw)

    async def exists(self, relative_path: str) -> bool:
        return self._abs(relative_path).exists()
