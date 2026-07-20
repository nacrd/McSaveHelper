"""Build a contiguous, viewport-sized map surface off the UI thread.

The Minecraft map mods keep a textured surface around the camera and move
that surface with a camera transform.  This module provides the same boundary
for Flet: one RGBA frame replaces hundreds of Canvas image shapes.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from threading import RLock
from typing import Callable, Mapping, Optional, Tuple

from PIL import Image, ImageDraw

RegionCoord = Tuple[int, int]
Color = Tuple[int, int, int]
CancelCheck = Callable[[], bool]


@dataclass(frozen=True)
class MapSurfaceSpec:
    """Immutable description of the world rectangle represented by a frame."""

    min_region_x: int
    max_region_x: int
    min_region_z: int
    max_region_z: int
    pixels_per_region: int
    display_mode: str = "topview"
    use_topview: bool = True
    source_generation: int = 0
    data_revision: int = 0

    def __post_init__(self) -> None:
        if self.max_region_x < self.min_region_x:
            raise ValueError("max_region_x must be greater than or equal to min_region_x")
        if self.max_region_z < self.min_region_z:
            raise ValueError("max_region_z must be greater than or equal to min_region_z")
        if self.pixels_per_region < 1:
            raise ValueError("pixels_per_region must be at least 1")
        if self.pixel_width * self.pixel_height > 16_000_000:
            raise ValueError("map surface exceeds the 16 megapixel safety limit")

    @property
    def columns(self) -> int:
        return max(1, self.max_region_x - self.min_region_x + 1)

    @property
    def rows(self) -> int:
        return max(1, self.max_region_z - self.min_region_z + 1)

    @property
    def pixel_width(self) -> int:
        return self.columns * max(1, int(self.pixels_per_region))

    @property
    def pixel_height(self) -> int:
        return self.rows * max(1, int(self.pixels_per_region))


@dataclass(frozen=True)
class MapSurfaceFrame:
    """RGBA pixels plus the world rectangle they cover."""

    pixels: bytes
    width: int
    height: int
    min_region_x: int
    min_region_z: int
    pixels_per_region: int
    spec: MapSurfaceSpec


class MapSurfaceRenderer:
    """Compose cached region tiles into one seamless RGBA frame."""

    def __init__(self, max_decoded_tiles: int = 192) -> None:
        self._max_decoded_tiles = max(16, int(max_decoded_tiles))
        self._decoded: OrderedDict[
            Tuple[int, RegionCoord, int, int], Image.Image
        ] = OrderedDict()
        self._lock = RLock()

    def invalidate(self, coord: Optional[RegionCoord] = None) -> None:
        """Drop decoded source images, optionally only for one region."""
        with self._lock:
            if coord is None:
                for image in self._decoded.values():
                    image.close()
                self._decoded.clear()
                return
            stale = [key for key in self._decoded if key[1] == coord]
            for key in stale:
                image = self._decoded.pop(key)
                image.close()

    def compose(
        self,
        spec: MapSurfaceSpec,
        data: Mapping[RegionCoord, int],
        tile_bytes: Mapping[RegionCoord, Optional[bytes]],
        tile_revisions: Mapping[RegionCoord, int],
        colors: Mapping[RegionCoord, Color],
        *,
        cancel_check: Optional[CancelCheck] = None,
    ) -> MapSurfaceFrame:
        """Compose a frame without touching Flet controls."""
        pixels_per_region = max(1, int(spec.pixels_per_region))
        min_x = spec.min_region_x
        min_z = spec.min_region_z
        with self._lock:
            image = Image.new(
                "RGBA",
                (spec.pixel_width, spec.pixel_height),
                (11, 18, 11, 255),
            )
            draw = ImageDraw.Draw(image)
            index = 0
            for region_z in range(min_z, spec.max_region_z + 1):
                for region_x in range(min_x, spec.max_region_x + 1):
                    index += 1
                    if (
                        cancel_check is not None
                        and index % 64 == 0
                        and cancel_check()
                    ):
                        image.close()
                        raise _SurfaceCancelled
                    coord = (region_x, region_z)
                    if coord not in data:
                        continue
                    x0 = (region_x - min_x) * pixels_per_region
                    y0 = (region_z - min_z) * pixels_per_region
                    x1 = x0 + pixels_per_region
                    y1 = y0 + pixels_per_region
                    raw = tile_bytes.get(coord)
                    if spec.use_topview and raw:
                        tile = self._decoded_tile(
                            spec.source_generation,
                            coord,
                            int(tile_revisions.get(coord, 0) or 0),
                            pixels_per_region,
                            raw,
                        )
                        if tile is not None:
                            image.paste(tile, (x0, y0))
                            continue
                    draw.rectangle(
                        (x0, y0, max(x0, x1 - 1), max(y0, y1 - 1)),
                        fill=_rgb(colors.get(coord, (42, 58, 46))),
                    )

            pixels = image.tobytes()
            image.close()
        return MapSurfaceFrame(
            pixels=pixels,
            width=spec.pixel_width,
            height=spec.pixel_height,
            min_region_x=min_x,
            min_region_z=min_z,
            pixels_per_region=pixels_per_region,
            spec=spec,
        )

    def _decoded_tile(
        self,
        source_generation: int,
        coord: RegionCoord,
        revision: int,
        pixels_per_region: int,
        raw: bytes,
    ) -> Optional[Image.Image]:
        key = (source_generation, coord, revision, pixels_per_region)
        with self._lock:
            cached = self._decoded.get(key)
            if cached is not None:
                self._decoded.move_to_end(key)
                return cached
        try:
            with Image.open(BytesIO(raw)) as source:
                # Region tiles are already contiguous in the composed image.
                # Use area filtering when reducing them and linear filtering
                # when a parent LOD is enlarged; nearest-neighbour sampling
                # makes coastlines and relief look like hard square steps.
                if source.width > pixels_per_region:
                    resampling = getattr(
                        Image.Resampling,
                        "BOX",
                        Image.Resampling.BILINEAR,
                    )
                else:
                    resampling = Image.Resampling.BILINEAR
                decoded = source.convert("RGB").resize(
                    (pixels_per_region, pixels_per_region),
                    resampling,
                )
        except Exception:
            return None
        with self._lock:
            self._decoded[key] = decoded
            self._decoded.move_to_end(key)
            while len(self._decoded) > self._max_decoded_tiles:
                _old_key, old_image = self._decoded.popitem(last=False)
                old_image.close()
        return decoded


class _SurfaceCancelled(Exception):
    """Internal cancellation marker for a superseded composition job."""


def _rgb(value: object) -> Color:
    if isinstance(value, tuple) and len(value) >= 3:
        try:
            return (int(value[0]), int(value[1]), int(value[2]))
        except (TypeError, ValueError):
            pass
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) in {6, 8}:
            try:
                return (
                    int(text[0:2], 16),
                    int(text[2:4], 16),
                    int(text[4:6], 16),
                )
            except ValueError:
                pass
    return (42, 58, 46)


__all__ = ["MapSurfaceFrame", "MapSurfaceRenderer", "MapSurfaceSpec"]
