"""Base64 source cache for canvas top-view tiles."""
from __future__ import annotations

import base64
from collections import OrderedDict
from typing import Callable, Optional, Tuple

RegionCoord = Tuple[int, int]
TileLoader = Callable[[RegionCoord], Optional[bytes]]


class TileSourceCache:
    """Cache canvas-ready base64 strings by service generation."""

    MAX_BYTES: int = 16 * 1024 * 1024

    def __init__(self) -> None:
        """创建空的瓦片源缓存。"""
        self._generation = -1
        self._sources: OrderedDict[RegionCoord, Tuple[int, str]] = OrderedDict()
        self._bytes = 0

    def get(
        self,
        coord: RegionCoord,
        *,
        generation: int,
        version: int = 0,
        load_tile: TileLoader,
    ) -> Optional[str]:
        """Return a cached/encoded tile, invalidating on generation change."""
        if generation != self._generation:
            self._sources.clear()
            self._bytes = 0
            self._generation = generation
        cached = self._sources.get(coord)
        if cached is not None and cached[0] == version:
            self._sources.move_to_end(coord)
            return cached[1]
        if cached is not None:
            self._sources.pop(coord, None)
            self._bytes -= len(cached[1])
        raw = load_tile(coord)
        if not raw:
            return None
        source = base64.b64encode(raw).decode("ascii")
        self._sources[coord] = (version, source)
        self._bytes += len(source)
        while self._bytes > self.MAX_BYTES and self._sources:
            _old_coord, (_version, old_source) = self._sources.popitem(last=False)
            self._bytes -= len(old_source)
        return source

    def clear(self) -> None:
        """清空全部缓存条目。"""
        self._sources.clear()
        self._bytes = 0
        self._generation = -1
