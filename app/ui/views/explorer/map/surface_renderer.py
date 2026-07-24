"""在 UI 线程外拼出连续、视口尺寸的地图表面。

地图模组通常缓存相机周围纹理表面，再通过相机变换移动。
本模块为 Flet 提供同样边界：一帧 RGBA 替代成百上千个 Canvas 图元。
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
    """一帧地图表面所覆盖世界矩形的不可变描述。

    Attributes:
        min_region_x: 区域 X 下界（含）。
        max_region_x: 区域 X 上界（含）。
        min_region_z: 区域 Z 下界（含）。
        max_region_z: 区域 Z 上界（含）。
        pixels_per_region: 每个 region 边长像素数。
        display_mode: 显示模式标签（如 topview）。
        use_topview: 是否优先贴俯视瓦片，否则退回纯色块。
        source_generation: 数据源代数，用于缓存失效。
        data_revision: 内容修订号，用于缓存失效。
    """

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
        """表面横向 region 列数（至少 1）。"""
        return max(1, self.max_region_x - self.min_region_x + 1)

    @property
    def rows(self) -> int:
        """表面纵向 region 行数（至少 1）。"""
        return max(1, self.max_region_z - self.min_region_z + 1)

    @property
    def pixel_width(self) -> int:
        """表面像素宽 = 列数 × 每 region 像素。"""
        return self.columns * max(1, int(self.pixels_per_region))

    @property
    def pixel_height(self) -> int:
        """表面像素高 = 行数 × 每 region 像素。"""
        return self.rows * max(1, int(self.pixels_per_region))


@dataclass(frozen=True)
class MapSurfaceFrame:
    """合成后的 RGBA 像素及其覆盖的世界矩形。

    Attributes:
        pixels: 行主序 RGBA 原始字节。
        width: 像素宽。
        height: 像素高。
        min_region_x: 左上角 region X。
        min_region_z: 左上角 region Z。
        pixels_per_region: 每 region 边长像素。
        spec: 生成该帧时使用的规格。
    """

    pixels: bytes
    width: int
    height: int
    min_region_x: int
    min_region_z: int
    pixels_per_region: int
    spec: MapSurfaceSpec


class MapSurfaceRenderer:
    """将缓存的区域瓦片合成为无缝隙的 RGBA 帧。

    解码瓦片有 LRU 上限；可在后台线程调用，不触碰 Flet 控件。
    """

    def __init__(self, max_decoded_tiles: int = 192) -> None:
        """创建渲染器并限制已解码瓦片缓存容量。

        Args:
            max_decoded_tiles: 解码缓存上限；小于 16 时抬升到 16。
        """
        self._max_decoded_tiles = max(16, int(max_decoded_tiles))
        self._decoded: OrderedDict[
            Tuple[int, RegionCoord, int, int], Image.Image
        ] = OrderedDict()
        self._lock = RLock()

    def invalidate(self, coord: Optional[RegionCoord] = None) -> None:
        """丢弃已解码源图；可仅针对单个 region。

        Args:
            coord: 可选 ``(rx, rz)``；None 时清空全部缓存。
        """
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

    def close(self) -> None:
        """关闭全部解码图像；可重复调用。"""
        self.invalidate()

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
        """合成一帧表面，不触碰 Flet 控件。

        Args:
            spec: 目标世界矩形与像素密度。
            data: 有数据的 region 集合（值为任意标记即可）。
            tile_bytes: region → 俯视瓦片 PNG 字节；缺失则画纯色。
            tile_revisions: region → 瓦片修订号，参与缓存键。
            colors: region → 回退填充 RGB。
            cancel_check: 可选取消探测；返回 True 时中止并抛内部取消。

        Returns:
            合成后的 ``MapSurfaceFrame``。
        """
        pixels_per_region = max(1, int(spec.pixels_per_region))
        min_x = spec.min_region_x
        min_z = spec.min_region_z
        with self._lock:
            image = Image.new(
                "RGBA",
                (spec.pixel_width, spec.pixel_height),
                (11, 18, 11, 255),
            )
            try:
                self._paint_surface_regions(
                    image=image,
                    spec=spec,
                    data=data,
                    tile_bytes=tile_bytes,
                    tile_revisions=tile_revisions,
                    colors=colors,
                    pixels_per_region=pixels_per_region,
                    min_x=min_x,
                    min_z=min_z,
                    cancel_check=cancel_check,
                )
                pixels = image.tobytes()
            finally:
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

    def _paint_surface_regions(
        self,
        *,
        image: Image.Image,
        spec: MapSurfaceSpec,
        data: Mapping[RegionCoord, int],
        tile_bytes: Mapping[RegionCoord, Optional[bytes]],
        tile_revisions: Mapping[RegionCoord, int],
        colors: Mapping[RegionCoord, Color],
        pixels_per_region: int,
        min_x: int,
        min_z: int,
        cancel_check: Optional[CancelCheck],
    ) -> None:
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
    """内部取消标记：合成任务已被更新的请求取代。"""


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
