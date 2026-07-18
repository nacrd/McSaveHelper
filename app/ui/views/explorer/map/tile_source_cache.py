"""Base64 source cache for canvas top-view tiles."""
from __future__ import annotations

import base64
from typing import Callable, Dict, Optional, Tuple

RegionCoord = Tuple[int, int]
TileLoader = Callable[[RegionCoord], Optional[bytes]]


class TileSourceCache:
    """Cache canvas-ready base64 strings by service generation."""

    def __init__(self) -> None:
        self._generation = -1
        self._sources: Dict[RegionCoord, str] = {}

    def get(
        self,
        coord: RegionCoord,
        *,
        generation: int,
        load_tile: TileLoader,
    ) -> Optional[str]:
        """Return a cached/encoded tile, invalidating on generation change."""
        if generation != self._generation:
            self._sources.clear()
            self._generation = generation
        cached = self._sources.get(coord)
        if cached is not None:
            return cached
        raw = load_tile(coord)
        if not raw:
            return None
        source = base64.b64encode(raw).decode("ascii")
        self._sources[coord] = source
        return source

    def clear(self) -> None:
        self._sources.clear()
        self._generation = -1
