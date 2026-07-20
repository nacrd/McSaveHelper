"""区域地图视口纯计算：缩放、平移与坐标投影。

与 UI 解耦，保证标记、瓦片与交互命中使用同一套变换不变量。
"""
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
    """根据相机 scale 映射语义细节层级。

    Args:
        scale: 当前视口缩放因子。

    Returns:
        MapViewLevel: world / region / chunk / block 之一。
    """
    if scale >= SCALE_BLOCK:
        return "block"
    if scale >= SCALE_CHUNK:
        return "chunk"
    if scale >= SCALE_REGION:
        return "region"
    return "world"


@dataclass
class McaMapSelection:
    """保持语义层级与 region/chunk 选中状态一致。

    不变量：level 为 world/region 时 chunk 必须为 None；选中 chunk 会同步
    推导所属 region。
    """

    level: MapViewLevel = "world"
    region: Optional[RegionCoord] = None
    chunk: Optional[ChunkCoord] = None

    def reset(self) -> None:
        """清空选中并回到世界总览层级。"""
        self.level = "world"
        self.region = None
        self.chunk = None

    def set_level(self, level: MapViewLevel) -> bool:
        """切换语义层级，必要时清除 chunk 选中。

        world/region 层不展示块内细节，因此强制 ``chunk = None``，避免 UI
        与相机状态出现「在区域层仍高亮旧区块」的不一致。

        Args:
            level: 目标语义层级。

        Returns:
            bool: 层级是否实际发生变化。
        """
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
        """选中一个 region，并清除 chunk 选中。

        Args:
            coord: 区域坐标 ``(rx, rz)``。
            level: 选中后的语义层级，默认 region。
        """
        self.region = coord
        self.chunk = None
        self.level = level

    def select_chunk(
        self,
        coord: ChunkCoord,
        level: MapViewLevel = "chunk",
    ) -> None:
        """选中世界 chunk，并推导所属 region。

        Args:
            coord: 世界区块坐标 ``(cx, cz)``。
            level: 选中后的语义层级，默认 chunk。
        """
        self.chunk = coord
        self.region = (
            coord[0] // CHUNKS_PER_SIDE,
            coord[1] // CHUNKS_PER_SIDE,
        )
        self.level = level


@dataclass(frozen=True)
class ViewportTarget:
    """不可变相机目标，用于直接跳转与动画插值。"""

    scale: float
    offset_x: float
    offset_y: float

    def interpolate(self, other: "ViewportTarget", progress: float) -> "ViewportTarget":
        """在两点之间线性插值，progress 钳制到 [0, 1]。

        Args:
            other: 插值终点。
            progress: 进度，越界会被钳制。

        Returns:
            ViewportTarget: 插值后的相机目标。
        """
        progress = max(0.0, min(1.0, float(progress)))
        return ViewportTarget(
            scale=self.scale + (other.scale - self.scale) * progress,
            offset_x=self.offset_x + (other.offset_x - self.offset_x) * progress,
            offset_y=self.offset_y + (other.offset_y - self.offset_y) * progress,
        )


@dataclass
class McaViewport:
    """可变相机状态；计算无副作用，便于测试与动画复用。"""

    scale: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    cell_size: float = 32.0
    cell_gap: float = 0.0
    min_scale: float = MIN_SCALE
    max_scale: float = MAX_SCALE

    @property
    def cell_pitch(self) -> float:
        """单个 region 格在地图平面上的步长（含可选间隙）。"""
        return self.cell_size + self.cell_gap

    @property
    def current_target(self) -> ViewportTarget:
        """当前相机状态的不可变快照。"""
        return ViewportTarget(self.scale, self.offset_x, self.offset_y)

    @property
    def is_default(self) -> bool:
        """是否仍为默认 scale=1 且无平移。"""
        return (
            self.scale == 1.0
            and self.offset_x == 0.0
            and self.offset_y == 0.0
        )

    def reset(self) -> None:
        """重置到默认相机（scale=1，offset=0）。"""
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0

    def apply(self, target: ViewportTarget) -> None:
        """应用目标相机；scale 会钳制到 [min_scale, max_scale]。

        Args:
            target: 目标相机状态。
        """
        self.scale = self._clamp_scale(target.scale)
        self.offset_x = float(target.offset_x)
        self.offset_y = float(target.offset_y)

    def pan(self, delta_x: float, delta_y: float) -> None:
        """按屏幕像素增量平移视口。

        Args:
            delta_x: 屏幕 X 方向增量。
            delta_y: 屏幕 Y 方向增量。
        """
        self.offset_x += float(delta_x)
        self.offset_y += float(delta_y)

    def world_to_screen(self, world_x: float, world_z: float) -> Tuple[float, float]:
        """地图平面坐标 → 屏幕像素。

        Args:
            world_x: 地图平面 X。
            world_z: 地图平面 Z。

        Returns:
            Tuple[float, float]: 屏幕 ``(sx, sy)``。
        """
        return (
            world_x * self.scale + self.offset_x,
            world_z * self.scale + self.offset_y,
        )

    def screen_to_world(self, screen_x: float, screen_y: float) -> Tuple[float, float]:
        """屏幕像素 → 地图平面坐标。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。

        Returns:
            Tuple[float, float]: 地图平面 ``(wx, wz)``。

        Raises:
            ValueError: scale 非正时无法求逆。
        """
        if self.scale <= 0:
            raise ValueError("Viewport scale must be positive")
        return (
            (screen_x - self.offset_x) / self.scale,
            (screen_y - self.offset_y) / self.scale,
        )

    def block_to_world(self, block_x: float, block_z: float) -> Tuple[float, float]:
        """将方块坐标投影到区域地图平面。

        统一放在此处，使标记、搜索结果与未来覆盖层与底图瓦片共用同一变换。

        Args:
            block_x: 世界方块 X。
            block_z: 世界方块 Z。

        Returns:
            Tuple[float, float]: 地图平面坐标。
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
        """方块坐标直接投影到屏幕像素。

        Args:
            block_x: 世界方块 X。
            block_z: 世界方块 Z。

        Returns:
            Tuple[float, float]: 屏幕坐标。
        """
        world_x, world_z = self.block_to_world(block_x, block_z)
        return self.world_to_screen(world_x, world_z)

    def world_to_block(
        self,
        world_x: float,
        world_z: float,
    ) -> Optional[Tuple[int, int]]:
        """地图平面点反投影为方块坐标。

        默认 cell_gap=0 时平面连续；非零间隙（遗留调用）在间隙内返回 None。

        Args:
            world_x: 地图平面 X。
            world_z: 地图平面 Z。

        Returns:
            Optional[Tuple[int, int]]: 方块坐标，或间隙内的 None。
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
        """屏幕像素反投影为方块坐标。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。

        Returns:
            Optional[Tuple[int, int]]: 方块坐标，或无效命中。
        """
        world_x, world_z = self.screen_to_world(screen_x, screen_y)
        return self.world_to_block(world_x, world_z)

    def nearest_block_at_screen(
        self,
        screen_x: float,
        screen_y: float,
    ) -> Tuple[int, int]:
        """返回最近方块，含遗留非零 cell_gap 时的间隙吸附。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。

        Returns:
            Tuple[int, int]: 最近方块坐标。
        """
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
        """计算 region 在屏幕上的矩形 ``(left, top, width, height)``。

        cell_gap=0 时对边界取整，避免相邻 Canvas 图在分数像素上出现发丝缝。

        Args:
            coord: 区域坐标。

        Returns:
            ScreenRect: 屏幕矩形。
        """
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
        """命中屏幕点下的 region；间隙或未收录坐标返回 None。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。
            available: 若给定，仅当坐标在集合中才命中。

        Returns:
            Optional[RegionCoord]: 命中的区域坐标。
        """
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
        """返回距屏幕点最近的 region 网格坐标。

        与 ``region_at_screen`` 不同，有意包含间隙与缺失区域，适合中心优先
        的瓦片队列。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。

        Returns:
            RegionCoord: 最近网格坐标。
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
        """命中屏幕点下的世界 chunk 坐标。

        Args:
            screen_x: 屏幕 X。
            screen_y: 屏幕 Y。
            available: 可选已加载 region 集合。

        Returns:
            Optional[ChunkCoord]: 世界区块坐标，或无效命中。
        """
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
        """计算视口内可见 region 的网格包围盒。

        Args:
            width: 视口像素宽。
            height: 视口像素高。
            margin: 额外边距（世界单位）；默认一个 cell_pitch。

        Returns:
            Tuple[int, int, int, int]: ``(min_x, max_x, min_z, max_z)``。

        Raises:
            ValueError: 有效 pitch 过小无法求网格。
        """
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
        """计算将指定 region 居中并约占视口的相机目标。

        不修改当前状态，便于动画插值后再 apply。

        Args:
            coord: 目标区域。
            width: 视口宽。
            height: 视口高。
            target_fill: 目标占短边比例，会钳制到合理范围。

        Returns:
            ViewportTarget: 聚焦后的相机目标。
        """
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
        """计算将指定 chunk 居中的相机目标（至少到 block 级 scale）。

        Args:
            coord: 世界区块坐标。
            width: 视口宽。
            height: 视口高。
            target_fill: 目标占短边比例。

        Returns:
            ViewportTarget: 聚焦后的相机目标。
        """
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
        """计算使一组 region 落入视口的 fit 相机。

        Args:
            coords: 需要容纳的区域坐标集合。
            width: 视口宽。
            height: 视口高。
            padding: 留白比例（0.2–1.0）。
            min_fit_scale: fit 结果下限。
            max_fit_scale: fit 结果上限。

        Returns:
            ViewportTarget: 适配后的目标；空集或无效尺寸时返回默认。
        """
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
        """以屏幕锚点缩放，使该点下的世界位置保持不动。

        Args:
            factor: 相对缩放倍率。
            pivot_x: 锚点屏幕 X。
            pivot_y: 锚点屏幕 Y。
            base: 基准相机；默认当前状态。

        Returns:
            ViewportTarget: 缩放后的目标（不修改 self）。
        """
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
