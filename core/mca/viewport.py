"""Pure viewport math for Minecraft region maps."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Collection, Iterable, Literal, Optional, Tuple

from core.mca.format import CHUNKS_PER_SIDE

BLOCKS_PER_REGION = CHUNKS_PER_SIDE * 16


RegionCoord = Tuple[int, int]
ChunkCoord = Tuple[int, int]
ScreenRect = Tuple[float, float, float, float]
MapViewLevel = Literal["world", "region", "chunk", "block"]

SCALE_REGION = 2.0
SCALE_CHUNK = 6.5
SCALE_BLOCK = 20.0
MIN_SCALE = 0.1
MAX_SCALE = 320.0


def view_level_from_scale(scale: float) -> MapViewLevel:
    """Map a camera scale to the semantic map detail level."""
    if scale >= SCALE_BLOCK:
        return "block"
    if scale >= SCALE_CHUNK:
        return "chunk"
    if scale >= SCALE_REGION:
        return "region"
    return "world"


@dataclass
class McaMapSelection:
    """Keep semantic map level and region/chunk selection consistent."""

    level: MapViewLevel = "world"
    region: Optional[RegionCoord] = None
    chunk: Optional[ChunkCoord] = None

    def reset(self) -> None:
        self.level = "world"
        self.region = None
        self.chunk = None

    def set_level(self, level: MapViewLevel) -> bool:
        changed = level != self.level
        self.level = level
        if level in {"world", "region"}:
            self.chunk = None
        return changed

    def select_region(
        self,
        coord: RegionCoord,
        level: MapViewLevel = "region",
    ) -> None:
        self.region = coord
        self.chunk = None
        self.level = level

    def select_chunk(
        self,
        coord: ChunkCoord,
        level: MapViewLevel = "chunk",
    ) -> None:
        self.chunk = coord
        self.region = (
            coord[0] // CHUNKS_PER_SIDE,
            coord[1] // CHUNKS_PER_SIDE,
        )
        self.level = level


@dataclass(frozen=True)
class ViewportTarget:
    """An immutable camera target used by direct moves and animations."""

    scale: float
    offset_x: float
    offset_y: float

    def interpolate(self, other: "ViewportTarget", progress: float) -> "ViewportTarget":
        progress = max(0.0, min(1.0, float(progress)))
        return ViewportTarget(
            scale=self.scale + (other.scale - self.scale) * progress,
            offset_x=self.offset_x + (other.offset_x - self.offset_x) * progress,
            offset_y=self.offset_y + (other.offset_y - self.offset_y) * progress,
        )


@dataclass
class McaViewport:
    """Mutable camera state with deterministic, side-effect-free calculations."""

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    cell_size: float = 32.0
    cell_gap: float = 0.0
    min_scale: float = MIN_SCALE
    max_scale: float = MAX_SCALE

    @property
    def cell_pitch(self) -> float:
        return self.cell_size + self.cell_gap

    @property
    def current_target(self) -> ViewportTarget:
        return ViewportTarget(self.scale, self.offset_x, self.offset_y)

    @property
    def is_default(self) -> bool:
        return (
            self.scale == 1.0
            and self.offset_x == 0.0
            and self.offset_y == 0.0
        )

    def reset(self) -> None:
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

    def apply(self, target: ViewportTarget) -> None:
        self.scale = self._clamp_scale(target.scale)
        self.offset_x = float(target.offset_x)
        self.offset_y = float(target.offset_y)

    def pan(self, delta_x: float, delta_y: float) -> None:
        self.offset_x += float(delta_x)
        self.offset_y += float(delta_y)

    def world_to_screen(self, world_x: float, world_z: float) -> Tuple[float, float]:
        return (
            world_x * self.scale + self.offset_x,
            world_z * self.scale + self.offset_y,
        )

    def screen_to_world(self, screen_x: float, screen_y: float) -> Tuple[float, float]:
        if self.scale <= 0:
            raise ValueError("Viewport scale must be positive")
        return (
            (screen_x - self.offset_x) / self.scale,
            (screen_y - self.offset_y) / self.scale,
        )

    def block_to_world(self, block_x: float, block_z: float) -> Tuple[float, float]:
        """Project Minecraft block coordinates into the region-map plane.

        Keeping this conversion here means markers, search results, and future
        overlay layers share exactly the same transform as the base tiles.
        """
        region_x = math.floor(float(block_x) / BLOCKS_PER_REGION)
        region_z = math.floor(float(block_z) / BLOCKS_PER_REGION)
        local_x = float(block_x) - region_x * BLOCKS_PER_REGION
        local_z = float(block_z) - region_z * BLOCKS_PER_REGION
        return (
            region_x * self.cell_pitch + local_x / BLOCKS_PER_REGION * self.cell_size,
            region_z * self.cell_pitch + local_z / BLOCKS_PER_REGION * self.cell_size,
        )

    def block_to_screen(self, block_x: float, block_z: float) -> Tuple[float, float]:
        """Project Minecraft block coordinates directly to screen pixels."""
        world_x, world_z = self.block_to_world(block_x, block_z)
        return self.world_to_screen(world_x, world_z)

    def world_to_block(
        self,
        world_x: float,
        world_z: float,
    ) -> Optional[Tuple[int, int]]:
        """Inverse-project a map-plane point to a block coordinate.

        With the default zero cell gap, every point belongs to one continuous
        region plane.  A non-zero gap remains supported for legacy callers and
        returns ``None`` inside that explicitly requested gap.
        """
        region_x = math.floor(float(world_x) / self.cell_pitch)
        region_z = math.floor(float(world_z) / self.cell_pitch)
        local_x = float(world_x) - region_x * self.cell_pitch
        local_z = float(world_z) - region_z * self.cell_pitch
        if not (0.0 <= local_x < self.cell_size and 0.0 <= local_z < self.cell_size):
            return None
        block_x = math.floor(local_x / self.cell_size * BLOCKS_PER_REGION)
        block_z = math.floor(local_z / self.cell_size * BLOCKS_PER_REGION)
        return (
            region_x * BLOCKS_PER_REGION + min(BLOCKS_PER_REGION - 1, block_x),
            region_z * BLOCKS_PER_REGION + min(BLOCKS_PER_REGION - 1, block_z),
        )

    def screen_to_block(
        self,
        screen_x: float,
        screen_y: float,
    ) -> Optional[Tuple[int, int]]:
        """Inverse-project screen pixels to Minecraft block coordinates."""
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        return self.world_to_block(world_x, world_z)

    def nearest_block_at_screen(
        self,
        screen_x: float,
        screen_y: float,
    ) -> Tuple[int, int]:
        """Return the closest block, including legacy non-zero cell gaps."""
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        return (
            self._nearest_block_axis(world_x),
            self._nearest_block_axis(world_z),
        )

    def _nearest_block_axis(self, world_value: float) -> int:
        region = math.floor(float(world_value) / self.cell_pitch)
        local = float(world_value) - region * self.cell_pitch
        if local >= self.cell_size:
            distance_to_previous = local - self.cell_size
            distance_to_next = self.cell_pitch - local
            if distance_to_next < distance_to_previous:
                region += 1
                local = 0.0
            else:
                local = math.nextafter(self.cell_size, 0.0)
        block = math.floor(local / self.cell_size * BLOCKS_PER_REGION)
        return region * BLOCKS_PER_REGION + min(BLOCKS_PER_REGION - 1, block)

    def region_rect(self, coord: RegionCoord) -> ScreenRect:
        left, top = self.world_to_screen(
            coord[0] * self.cell_pitch,
            coord[1] * self.cell_pitch,
        )
        right, bottom = self.world_to_screen(
            coord[0] * self.cell_pitch + self.cell_size,
            coord[1] * self.cell_pitch + self.cell_size,
        )
        if self.cell_gap == 0.0:
            # Shared rounded edges prevent hairline seams when separate Canvas
            # images land on fractional pixels. Adjacent regions calculate the
            # same boundary from the same world coordinate.
            left = float(round(left))
            top = float(round(top))
            right = float(round(right))
            bottom = float(round(bottom))
        return left, top, max(0.0, right - left), max(0.0, bottom - top)

    def region_at_screen(
        self,
        screen_x: float,
        screen_y: float,
        available: Optional[Collection[RegionCoord]] = None,
    ) -> Optional[RegionCoord]:
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        region_x = math.floor(world_x / self.cell_pitch)
        region_z = math.floor(world_z / self.cell_pitch)
        local_x = world_x - region_x * self.cell_pitch
        local_z = world_z - region_z * self.cell_pitch
        if not (0 <= local_x < self.cell_size and 0 <= local_z < self.cell_size):
            return None
        coord = (int(region_x), int(region_z))
        if available is not None and coord not in available:
            return None
        return coord

    def nearest_region_at_screen(
        self,
        screen_x: float,
        screen_y: float,
    ) -> RegionCoord:
        """Return the region grid coordinate nearest a screen point.

        Unlike ``region_at_screen``, this intentionally includes cell gaps and
        absent regions, which makes it suitable for center-first tile queues.
        """
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        return (
            int(math.floor(world_x / self.cell_pitch)),
            int(math.floor(world_z / self.cell_pitch)),
        )

    def chunk_at_screen(
        self,
        screen_x: float,
        screen_y: float,
        available: Optional[Collection[RegionCoord]] = None,
    ) -> Optional[ChunkCoord]:
        region = self.region_at_screen(screen_x, screen_y, available)
        if region is None:
            return None
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        local_x = world_x - region[0] * self.cell_pitch
        local_z = world_z - region[1] * self.cell_pitch
        chunk_size = self.cell_size / CHUNKS_PER_SIDE
        local_chunk_x = min(
            CHUNKS_PER_SIDE - 1,
            max(0, math.floor(local_x / chunk_size)),
        )
        local_chunk_z = min(
            CHUNKS_PER_SIDE - 1,
            max(0, math.floor(local_z / chunk_size)),
        )
        return (
            region[0] * CHUNKS_PER_SIDE + int(local_chunk_x),
            region[1] * CHUNKS_PER_SIDE + int(local_chunk_z),
        )

    def visible_region_bounds(
        self,
        width: float,
        height: float,
        margin: Optional[float] = None,
    ) -> Tuple[int, int, int, int]:
        margin = self.cell_pitch if margin is None else max(0.0, float(margin))
        pitch_scaled = self.cell_pitch * self.scale
        if pitch_scaled <= 1e-6:
            raise ValueError("Viewport scale is too small")
        min_x = math.floor((0.0 - margin - self.offset_x) / pitch_scaled)
        max_x = math.ceil((width + margin - self.offset_x) / pitch_scaled)
        min_z = math.floor((0.0 - margin - self.offset_y) / pitch_scaled)
        max_z = math.ceil((height + margin - self.offset_y) / pitch_scaled)
        return int(min_x), int(max_x), int(min_z), int(max_z)

    def focus_region(
        self,
        coord: RegionCoord,
        width: float,
        height: float,
        target_fill: float = 0.72,
    ) -> ViewportTarget:
        fill = max(0.35, min(0.95, float(target_fill)))
        desired = min(width, height) * fill
        scale = self._clamp_scale(desired / self.cell_size)
        world_x = (coord[0] + 0.5) * self.cell_pitch
        world_z = (coord[1] + 0.5) * self.cell_pitch
        return ViewportTarget(
            scale,
            width / 2.0 - world_x * scale,
            height / 2.0 - world_z * scale,
        )

    def focus_chunk(
        self,
        coord: ChunkCoord,
        width: float,
        height: float,
        target_fill: float = 0.78,
    ) -> ViewportTarget:
        region_x, local_x = divmod(coord[0], CHUNKS_PER_SIDE)
        region_z, local_z = divmod(coord[1], CHUNKS_PER_SIDE)
        chunk_size = self.cell_size / CHUNKS_PER_SIDE
        world_x = region_x * self.cell_pitch + (local_x + 0.5) * chunk_size
        world_z = region_z * self.cell_pitch + (local_z + 0.5) * chunk_size
        fill = max(0.4, min(0.95, float(target_fill)))
        desired = min(width, height) * fill
        scale = max(SCALE_BLOCK, self._clamp_scale(desired / chunk_size))
        return ViewportTarget(
            scale,
            width / 2.0 - world_x * scale,
            height / 2.0 - world_z * scale,
        )

    def fit(
        self,
        coords: Iterable[RegionCoord],
        width: float,
        height: float,
        padding: float = 0.86,
        min_fit_scale: float = 0.2,
        max_fit_scale: float = 8.0,
    ) -> ViewportTarget:
        points = tuple(coords)
        if not points or width <= 1 or height <= 1:
            return ViewportTarget(1.0, 0.0, 0.0)
        min_x = min(coord[0] for coord in points)
        max_x = max(coord[0] for coord in points)
        min_z = min(coord[1] for coord in points)
        max_z = max(coord[1] for coord in points)
        world_left = min_x * self.cell_pitch
        world_right = max_x * self.cell_pitch + self.cell_size
        world_top = min_z * self.cell_pitch
        world_bottom = max_z * self.cell_pitch + self.cell_size
        world_width = max(self.cell_size, world_right - world_left)
        world_height = max(self.cell_size, world_bottom - world_top)
        pad = max(0.2, min(1.0, float(padding)))
        scale = min(width / world_width * pad, height / world_height * pad)
        scale = max(min_fit_scale, min(scale, max_fit_scale))
        center_x = (world_left + world_right) / 2.0
        center_z = (world_top + world_bottom) / 2.0
        return ViewportTarget(
            scale,
            width / 2.0 - center_x * scale,
            height / 2.0 - center_z * scale,
        )

    def zoom_about(
        self,
        factor: float,
        pivot_x: float,
        pivot_y: float,
        base: Optional[ViewportTarget] = None,
    ) -> ViewportTarget:
        base = base or self.current_target
        new_scale = self._clamp_scale(base.scale * float(factor))
        if base.scale <= 0:
            return ViewportTarget(new_scale, base.offset_x, base.offset_y)
        world_x = (pivot_x - base.offset_x) / base.scale
        world_y = (pivot_y - base.offset_y) / base.scale
        return ViewportTarget(
            new_scale,
            pivot_x - world_x * new_scale,
            pivot_y - world_y * new_scale,
        )

    def _clamp_scale(self, scale: float) -> float:
        return max(self.min_scale, min(float(scale), self.max_scale))
