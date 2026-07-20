"""Topview 瓦片请求协调。

该模块只负责把视口需求转换为服务请求，并维护有界队列所需的轻量账本。
它不依赖 Flet；后台完成回调和 UI 重建之间的线程切换仍由视图负责。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Collection, Dict, Iterable, List, Mapping, Optional, Protocol, Set, Tuple

from core.mca.map_tiles import (
    HIGH_DETAIL_TILE_LADDER,
    MapTileRequest,
    choose_tile_size,
    plan_visible_requests,
)
from core.mca.topview_renderer import (
    DETAIL_TILE_SIZE,
    LEAF_TILE_SIZE,
    PREVIEW_TILE_SIZE,
    ULTRA_TILE_SIZE,
)


RegionCoord = Tuple[int, int]


class TopviewTileServicePort(Protocol):
    """瓦片协调器使用的服务最小端口。"""

    def has_topview_tile(self, coord: RegionCoord, min_size: int = 0) -> bool:
        """是否已有不低于 ``min_size`` 的可用瓦片。

        Args:
            coord: 区域坐标。
            min_size: 最小边长；0 表示任意缓存。

        Returns:
            是否可直接使用。
        """
        ...

    def get_topview_tile_size(self, coord: RegionCoord) -> int:
        """返回已缓存瓦片边长。

        Args:
            coord: 区域坐标。

        Returns:
            像素边长；无缓存为 0。
        """
        ...

    def is_topview_tile_pending(
        self,
        coord: RegionCoord,
        *,
        min_size: int = 0,
    ) -> bool:
        """服务当前代数是否仍持有该坐标的请求。

        Args:
            coord: 区域坐标。
            min_size: 要求的最小请求尺寸。

        Returns:
            是否仍在队列或升级账本中。
        """
        ...

    def request_topview_tiles(
        self,
        coords: List[RegionCoord],
        tile_size: Optional[int] = None,
        *,
        force: bool = False,
        priority: bool = False,
    ) -> Set[RegionCoord]:
        """向服务提交渲染请求。

        Args:
            coords: 区域坐标列表。
            tile_size: 目标边长。
            force: 是否强制升级/优先不完整瓦片。
            priority: 是否插队。

        Returns:
            服务实际接纳的坐标集合。
        """
        ...


@dataclass(frozen=True)
class TopviewTileRequestPolicy:
    """地图瓦片的可见请求和聚焦升级策略。"""

    cell_size: float = 32.0
    source_oversample: float = 2.0
    leaf_scale: float = 8.0
    focus_scale: float = 2.2
    visible_batch_limit: int = 64
    preview_upgrade_threshold: int = 32
    preview_size: int = PREVIEW_TILE_SIZE
    detail_size: int = DETAIL_TILE_SIZE
    visible_max_size: int = ULTRA_TILE_SIZE
    leaf_size: int = LEAF_TILE_SIZE


class TopviewTileRequestCoordinator:
    """协调可见瓦片、聚焦细节及队列容量重试。

    线程安全：账本由内部锁保护。不取消服务已接收任务；``reset`` 只清视图侧
    账本。完成回调与 UI 重建之间的线程切换由视图负责。
    """

    def __init__(
        self,
        service: TopviewTileServicePort,
        policy: TopviewTileRequestPolicy = TopviewTileRequestPolicy(),
    ) -> None:
        """绑定服务端口与请求策略。

        Args:
            service: 俯视瓦片服务端口（通常为 RegionMapService）。
            policy: LOD/批量/聚焦策略；默认使用模块常量。
        """
        self._service = service
        self._policy = policy
        self._requested_sizes: Dict[RegionCoord, int] = {}
        self._has_deferred_requests = False
        self._state_lock = threading.Lock()

    @property
    def requested_sizes(self) -> Dict[RegionCoord, int]:
        """返回当前服务仍持有的可见请求账本快照。"""
        with self._state_lock:
            return dict(self._requested_sizes)

    @property
    def has_deferred_requests(self) -> bool:
        """是否仍有因队列满而推迟的可见请求。"""
        with self._state_lock:
            return self._has_deferred_requests

    def reset(self) -> None:
        """丢弃视图侧账本；不会取消服务已接收的渲染任务。"""
        with self._state_lock:
            self._requested_sizes.clear()
            self._has_deferred_requests = False

    def on_tile_ready(self, coord: RegionCoord) -> bool:
        """记录完成事件，并返回是否需要借此机会重试被拒绝的请求。

        Args:
            coord: 刚就绪的区域坐标。

        Returns:
            若存在推迟请求则为 True，调用方应再次 ``request_visible``。
        """
        with self._state_lock:
            self._requested_sizes.pop(coord, None)
            return self._has_deferred_requests

    def visible_tile_size(self, scale: float) -> int:
        """返回当前显示所需 LOD；512 仅用于后续聚焦升级。

        Args:
            scale: 当前地图缩放。

        Returns:
            建议瓦片边长。
        """
        return choose_tile_size(
            self._screen_tile_pixels(scale),
            self._tile_ladder(scale),
        )

    def visible_base_tile_size(self, scale: float) -> int:
        """返回普通帧 LOD，排除聚焦用 512 叶节点。

        Args:
            scale: 当前地图缩放。

        Returns:
            不超过 ``visible_max_size`` 的边长。
        """
        return min(
            self.visible_tile_size(scale),
            self._policy.visible_max_size,
        )

    def request_visible(
        self,
        missing: Iterable[RegionCoord],
        *,
        visible_regions: Collection[RegionCoord],
        scale: float,
        center: RegionCoord,
    ) -> None:
        """请求当前视口缺失瓦片，并记录服务队列未接收的尾部。

        Args:
            missing: 视口内尚无瓦片的坐标。
            visible_regions: 当前视口全部区域（用于账本对账）。
            scale: 地图缩放。
            center: 视口中心区域坐标。
        """
        requests = plan_visible_requests(
            missing,
            screen_tile_pixels=self._screen_tile_pixels(scale),
            center=center,
            ladder=self._tile_ladder(scale),
        )
        missing_coords = {request.coord for request in requests}
        visible_coords = set(visible_regions)
        with self._state_lock:
            self._reconcile_visible_ledger(missing_coords, visible_coords)
            grouped, selected_count, has_more = self._select_visible_batch(requests)
            accepted_count = self._submit_visible_groups(grouped)
            self._has_deferred_requests = (
                has_more or accepted_count < selected_count
            )

    def request_selected_detail(
        self,
        *,
        scale: float,
        selected: Optional[RegionCoord],
        center: RegionCoord,
        available_regions: Collection[RegionCoord],
        enabled: bool,
    ) -> Set[RegionCoord]:
        """升级选中区域；高倍率无选中项时只升级视口中心区域。

        Args:
            scale: 地图缩放。
            selected: 用户选中区域；None 时可能用中心。
            center: 视口中心区域。
            available_regions: 世界内已知区域集合。
            enabled: 是否启用聚焦升级。

        Returns:
            服务接纳的细节请求坐标集合。
        """
        if not enabled or scale < self._policy.focus_scale:
            return set()
        visible_size = self.visible_tile_size(scale)
        target = self._detail_target(selected, center, available_regions, visible_size)
        if target is None:
            return set()
        detail_size = max(self._policy.detail_size, visible_size)
        nearby = self._detail_regions(target, available_regions, detail_size)
        missing = [
            coord
            for coord in nearby
            if not self._service.has_topview_tile(coord, min_size=detail_size)
        ]
        return self.request_detail(
            missing,
            tile_size=detail_size,
            force=True,
            priority=True,
        )

    def request_region_detail(
        self,
        coord: RegionCoord,
        available_regions: Collection[RegionCoord],
    ) -> Set[RegionCoord]:
        """优先请求聚焦区域及其已有的八个邻区。

        Args:
            coord: 聚焦区域。
            available_regions: 世界内已知区域。

        Returns:
            服务接纳的坐标集合。
        """
        nearby = [
            (coord[0] + dx, coord[1] + dz)
            for dz in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (coord[0] + dx, coord[1] + dz) in available_regions
            or (dx, dz) == (0, 0)
        ]
        return self.request_detail(nearby, force=True, priority=True)

    def request_detail(
        self,
        coords: Iterable[RegionCoord],
        *,
        tile_size: Optional[int] = None,
        force: bool = False,
        priority: bool = False,
    ) -> Set[RegionCoord]:
        """提交显式细节请求，保留旧服务端口的参数兼容行为。

        Args:
            coords: 待升级坐标。
            tile_size: 目标边长；缺省用策略 ``detail_size``。
            force: 是否强制升级。
            priority: 是否插队。

        Returns:
            服务接纳的坐标集合。
        """
        requested = list(dict.fromkeys(coords))
        if not requested:
            return set()
        size = tile_size or self._policy.detail_size
        try:
            accepted = self._service.request_topview_tiles(
                requested,
                tile_size=size,
                force=force,
                priority=priority,
            )
        except TypeError:
            accepted = self._service.request_topview_tiles(
                requested,
                tile_size=size,
            )
        return set(accepted or ())

    def _screen_tile_pixels(self, scale: float) -> float:
        return self._policy.cell_size * max(float(scale), 0.01) * (
            self._policy.source_oversample
        )

    def _tile_ladder(self, scale: float) -> Tuple[int, ...]:
        if scale >= self._policy.leaf_scale:
            return HIGH_DETAIL_TILE_LADDER
        return HIGH_DETAIL_TILE_LADDER[:-1]

    def _reconcile_visible_ledger(
        self,
        missing: Set[RegionCoord],
        visible: Set[RegionCoord],
    ) -> None:
        for coord, requested_size in tuple(self._requested_sizes.items()):
            if coord not in visible or coord not in missing:
                self._requested_sizes.pop(coord, None)
                continue
            if not self._service.is_topview_tile_pending(
                coord,
                min_size=requested_size,
            ):
                self._requested_sizes.pop(coord, None)

    def _select_visible_batch(
        self,
        requests: Iterable[MapTileRequest],
    ) -> Tuple[Dict[int, List[RegionCoord]], int, bool]:
        grouped: Dict[int, List[RegionCoord]] = {}
        selected_count = 0
        for request in requests:
            requested_size = self._visible_request_size(request)
            if self._requested_sizes.get(request.coord, 0) >= requested_size:
                continue
            if selected_count >= self._policy.visible_batch_limit:
                return grouped, selected_count, True
            grouped.setdefault(requested_size, []).append(request.coord)
            selected_count += 1
        return grouped, selected_count, False

    def _visible_request_size(self, request: MapTileRequest) -> int:
        requested_size = min(request.tile_size, self._policy.visible_max_size)
        if (
            requested_size > self._policy.preview_upgrade_threshold
            and self._service.get_topview_tile_size(request.coord) <= 0
        ):
            return self._policy.preview_size
        return requested_size

    def _submit_visible_groups(
        self,
        grouped: Mapping[int, List[RegionCoord]],
    ) -> int:
        accepted_count = 0
        for tile_size, coords in grouped.items():
            accepted = self._service.request_topview_tiles(
                coords,
                tile_size=tile_size,
            )
            accepted_coords = set(accepted or ()).intersection(coords)
            accepted_count += len(accepted_coords)
            for coord in accepted_coords:
                self._requested_sizes[coord] = tile_size
        return accepted_count

    def _detail_target(
        self,
        selected: Optional[RegionCoord],
        center: RegionCoord,
        available: Collection[RegionCoord],
        visible_size: int,
    ) -> Optional[RegionCoord]:
        if selected is not None:
            return selected
        if visible_size >= self._policy.leaf_size and center in available:
            return center
        return None

    def _detail_regions(
        self,
        target: RegionCoord,
        available: Collection[RegionCoord],
        detail_size: int,
    ) -> List[RegionCoord]:
        if detail_size >= self._policy.leaf_size:
            return [target]
        return [
            (target[0] + dx, target[1] + dz)
            for dz in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (target[0] + dx, target[1] + dz) in available
        ]


__all__ = [
    "TopviewTileRequestCoordinator",
    "TopviewTileRequestPolicy",
    "TopviewTileServicePort",
]
