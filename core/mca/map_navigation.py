"""Pure selection and semantic-level navigation for MCA map UIs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from core.mca.map_coordinates import (
    format_chunk_block_range,
    format_region_block_range,
)
from core.mca.viewport import (
    ChunkCoord,
    MapViewLevel,
    McaMapSelection,
    RegionCoord,
)


@dataclass(frozen=True)
class SelectionNotification:
    """UI-neutral payload describing the current semantic selection."""

    region: Optional[RegionCoord]
    size: Optional[int]
    detail: Dict[str, Any]


@dataclass(frozen=True)
class LevelChange:
    """Describe direction and result of a semantic map-level transition."""

    previous: MapViewLevel
    current: MapViewLevel

    @property
    def changed(self) -> bool:
        return self.previous != self.current

    @property
    def going_deeper(self) -> bool:
        return _LEVEL_ORDER[self.current] > _LEVEL_ORDER[self.previous]

    @property
    def going_out(self) -> bool:
        return _LEVEL_ORDER[self.current] < _LEVEL_ORDER[self.previous]


_LEVEL_ORDER = {"world": 0, "region": 1, "chunk": 2, "block": 3}


class McaMapNavigator:
    """Coordinate selection invariants and callback payload construction."""

    def __init__(self, selection: Optional[McaMapSelection] = None) -> None:
        self.selection = selection or McaMapSelection()

    def select_region(
        self,
        coord: RegionCoord,
        region_sizes: Mapping[RegionCoord, int],
        level: MapViewLevel = "region",
    ) -> SelectionNotification:
        self.selection.select_region(coord, level)
        return self.current_notification(region_sizes)

    def select_chunk(
        self,
        coord: ChunkCoord,
        region_sizes: Mapping[RegionCoord, int],
        level: MapViewLevel = "chunk",
    ) -> SelectionNotification:
        self.selection.select_chunk(coord, level)
        return self.current_notification(region_sizes)

    def transition_to(self, level: MapViewLevel) -> LevelChange:
        previous = self.selection.level
        self.selection.set_level(level)
        return LevelChange(previous, self.selection.level)

    def step_back(
        self,
        region_sizes: Mapping[RegionCoord, int],
    ) -> SelectionNotification:
        if self.selection.level == "block":
            self.selection.set_level("chunk")
        elif self.selection.level == "chunk":
            self.selection.set_level("region")
        else:
            self.selection.set_level("world")
        return self.current_notification(region_sizes)

    def current_notification(
        self,
        region_sizes: Mapping[RegionCoord, int],
        level: Optional[MapViewLevel] = None,
    ) -> SelectionNotification:
        current_level = level or self.selection.level
        region = self.selection.region
        if current_level == "world" or region is None:
            return SelectionNotification(None, None, {"level": "world"})
        detail: Dict[str, Any] = {"level": current_level}
        chunk = self.selection.chunk
        if chunk is not None and current_level in {"chunk", "block"}:
            detail["chunk_coord"] = chunk
            detail["block_range"] = format_chunk_block_range(chunk)
        else:
            detail["block_range"] = format_region_block_range(region)
        return SelectionNotification(
            region,
            region_sizes.get(region, 0),
            detail,
        )
