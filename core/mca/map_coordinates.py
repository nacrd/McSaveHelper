"""Pure coordinate helpers shared by MCA map presentations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .viewport import MapViewLevel


MapCoordinate = Tuple[int, int]


@dataclass(frozen=True)
class BlockBounds:
    """Inclusive X/Z bounds in Minecraft block coordinates."""

    min_x: int
    max_x: int
    min_z: int
    max_z: int

    def format(self) -> str:
        """格式化为 ``X a~b, Z c~d`` 的人类可读区间。"""
        return (
            f"X {self.min_x}~{self.max_x}, "
            f"Z {self.min_z}~{self.max_z}"
        )


def region_block_bounds(coord: MapCoordinate) -> BlockBounds:
    """区域坐标 → 该区域覆盖的 512×512 方块闭区间。

    Args:
        coord: ``(region_x, region_z)``。

    Returns:
        含边界方块的 :class:`BlockBounds`。
    """
    region_x, region_z = coord
    min_x = region_x * 512
    min_z = region_z * 512
    return BlockBounds(min_x, min_x + 511, min_z, min_z + 511)


def chunk_block_bounds(coord: MapCoordinate) -> BlockBounds:
    """世界区块坐标 → 该区块 16×16 方块闭区间。

    Args:
        coord: ``(chunk_x, chunk_z)``。
    """
    chunk_x, chunk_z = coord
    min_x = chunk_x * 16
    min_z = chunk_z * 16
    return BlockBounds(min_x, min_x + 15, min_z, min_z + 15)


def format_region_block_range(coord: MapCoordinate) -> str:
    """区域坐标的方块范围字符串（选择详情/状态栏用）。"""
    return region_block_bounds(coord).format()


def format_chunk_block_range(coord: MapCoordinate) -> str:
    """区块坐标的方块范围字符串。"""
    return chunk_block_bounds(coord).format()


def format_region_coordinate_label(
    coord: MapCoordinate,
    *,
    view_level: MapViewLevel,
    scale: float,
    cell_size: float,
) -> str:
    """Choose region indices, ranges, or center blocks for the current zoom."""
    region_x, region_z = coord
    bounds = region_block_bounds(coord)
    if view_level in {"chunk", "block"} or scale >= 6.0 or cell_size >= 180:
        return f"{bounds.min_x + 256}, {bounds.min_z + 256}"
    if scale >= 2.4 or cell_size >= 70:
        if cell_size >= 90:
            return (
                f"X{bounds.min_x}~{bounds.max_x}\n"
                f"Z{bounds.min_z}~{bounds.max_z}"
            )
        return f"{bounds.min_x}~{bounds.max_x}"
    return f"{region_x},{region_z}"
