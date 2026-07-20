"""MCA 地图 UI 的纯选择与语义层级导航。

与 Flet 解耦：只维护选中不变量并构造回调载荷。
"""
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
    """描述当前语义选中的 UI 无关载荷。"""

    region: Optional[RegionCoord]
    size: Optional[int]
    detail: Dict[str, Any]


@dataclass(frozen=True)
class LevelChange:
    """描述语义地图层级切换的方向与结果。"""

    previous: MapViewLevel
    current: MapViewLevel

    @property
    def changed(self) -> bool:
        """层级是否实际变化。"""
        return self.previous != self.current

    @property
    def going_deeper(self) -> bool:
        """是否向更细层级进入（world→…→block）。"""
        return _LEVEL_ORDER[self.current] > _LEVEL_ORDER[self.previous]

    @property
    def going_out(self) -> bool:
        """是否向更粗层级退出。"""
        return _LEVEL_ORDER[self.current] < _LEVEL_ORDER[self.previous]


_LEVEL_ORDER = {"world": 0, "region": 1, "chunk": 2, "block": 3}


class McaMapNavigator:
    """协调选中不变量并构造回调载荷。"""

    def __init__(self, selection: Optional[McaMapSelection] = None) -> None:
        """绑定或新建 ``McaMapSelection``。

        Args:
            selection: 外部共享的选中状态；None 时新建默认。
        """
        self.selection = selection or McaMapSelection()

    def select_region(
        self,
        coord: RegionCoord,
        region_sizes: Mapping[RegionCoord, int],
        level: MapViewLevel = "region",
    ) -> SelectionNotification:
        """选中区域并返回通知载荷。

        Args:
            coord: 区域坐标。
            region_sizes: 区域大小查找表（字节等）。
            level: 选中后语义层级。

        Returns:
            SelectionNotification: 供 UI/controller 消费的载荷。
        """
        self.selection.select_region(coord, level)
        return self.current_notification(region_sizes)

    def select_chunk(
        self,
        coord: ChunkCoord,
        region_sizes: Mapping[RegionCoord, int],
        level: MapViewLevel = "chunk",
    ) -> SelectionNotification:
        """选中区块并返回通知载荷。

        Args:
            coord: 世界区块坐标。
            region_sizes: 区域大小查找表。
            level: 选中后语义层级。

        Returns:
            SelectionNotification: 当前选中通知。
        """
        self.selection.select_chunk(coord, level)
        return self.current_notification(region_sizes)

    def transition_to(self, level: MapViewLevel) -> LevelChange:
        """切换语义层级（world/region 时会清除 chunk 选中）。

        Args:
            level: 目标层级。

        Returns:
            LevelChange: 切换前后层级描述。
        """
        previous = self.selection.level
        self.selection.set_level(level)
        return LevelChange(previous, self.selection.level)

    def step_back(
        self,
        region_sizes: Mapping[RegionCoord, int],
    ) -> SelectionNotification:
        """逐级退出：block→chunk→region→world。

        Args:
            region_sizes: 区域大小查找表。

        Returns:
            SelectionNotification: 退出后的选中通知。
        """
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
        """按当前（或覆盖）层级构造选中通知。

        world 或未选 region 时返回无 region 的 world 载荷。

        Args:
            region_sizes: 区域大小查找表。
            level: 可选覆盖层级；默认使用 selection.level。

        Returns:
            SelectionNotification: 含 block_range 等 detail 字段。
        """
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
