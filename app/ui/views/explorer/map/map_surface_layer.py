"""Flet RawImage adapter for the buffered MCA map surface.

This module owns the FBO-like lifecycle used by the map view: quantized LOD,
buffered bounds, one background compose/upload at a time, and cheap camera
geometry updates while the user pans or zooms.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from typing import TYPE_CHECKING, Callable, Coroutine, Dict, Mapping, Optional, Tuple

import flet as ft

from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    OperationHandle,
    TaskPriority,
)
from app.ui.utils import ScheduledTask, safe_update
from app.ui.views.explorer.map.surface_renderer import (
    MapSurfaceFrame,
    MapSurfaceRenderer,
    MapSurfaceSpec,
    _rgb,
)
from core.logger import logger
from core.mca.map_tiles import HIGH_DETAIL_TILE_LADDER, choose_tile_size
from core.mca.topview_renderer import ULTRA_TILE_SIZE
from core.mca.viewport import McaViewport

if TYPE_CHECKING:
    from app.services.region_map import RegionMapService


RegionCoord = Tuple[int, int]
RgbColor = Tuple[int, int, int]
RegionBounds = Tuple[int, int, int, int]
ColorProvider = Callable[[RegionCoord, int], str]
TaskScheduler = Callable[[Coroutine[object, object, object]], Optional[ScheduledTask]]


@dataclass(frozen=True)
class _RenderRequest:
    """一次后台合成请求的不可变快照（内部用）。"""

    spec: MapSurfaceSpec
    data: Dict[RegionCoord, int]
    colors: Dict[RegionCoord, RgbColor]
    token: int
    tile_bytes: Dict[RegionCoord, bytes]
    tile_revisions: Dict[RegionCoord, int]


class MapSurfaceLayer:
    """持有一块缓冲 RawImage 及其异步替换帧。

    负责量化 LOD、缓冲边界、同一时刻仅一次后台 compose/upload，
    以及用户平移/缩放时的廉价相机几何更新。
    """

    SOURCE_OVERSAMPLE = 2.0

    def __init__(
        self,
        service: RegionMapService,
        *,
        execution_runtime: ExecutionRuntime,
        schedule_task: TaskScheduler,
        request_rebuild: Callable[[], None],
        is_active: Callable[[], bool],
        background_color: str,
        on_ready: Optional[Callable[[], None]] = None,
        on_unavailable: Optional[Callable[[Exception], None]] = None,
        cell_size: float = 32.0,
        buffer_regions: int = 2,
        max_regions: int = 192,
        max_pixels: int = 6_000_000,
    ) -> None:
        """绑定服务与调度回调，并尝试创建 RawImage 宿主。

        Args:
            service: 区域地图数据与俯视瓦片服务。
            execution_runtime: 应用级有界后台运行时。
            schedule_task: 将协程调度到 UI 任务循环。
            request_rebuild: 需要重绘时回调宿主。
            is_active: 图层所属页面是否仍活跃。
            background_color: 缓冲表面背景色。
            on_ready: 第一帧成功上传后的通知回调。
            on_unavailable: RawImage 运行时不可用时的通知回调。
            cell_size: 单区域基础像素边长。
            buffer_regions: 可见区外缓冲环数。
            max_regions: 单轴最大区域数。
            max_pixels: 表面像素预算上限。
        """
        self._service = service
        self._execution_runtime = execution_runtime
        self._schedule_task = schedule_task
        self._request_rebuild = request_rebuild
        self._is_active = is_active
        self._on_ready = on_ready
        self._on_unavailable = on_unavailable
        self._cell_size = max(1.0, float(cell_size))
        self._buffer_regions = max(1, int(buffer_regions))
        self._max_regions = max(8, int(max_regions))
        self._max_pixels = max(1_000_000, int(max_pixels))

        self._renderer = MapSurfaceRenderer()
        self._frame: Optional[MapSurfaceFrame] = None
        self._spec: Optional[MapSurfaceSpec] = None
        self._task: Optional[ScheduledTask] = None
        self._compose_handle: Optional[OperationHandle[MapSurfaceFrame]] = None
        self._lifecycle_lock = Lock()
        self._closed = False
        self._request_spec: Optional[MapSurfaceSpec] = None
        self._request_data: Dict[RegionCoord, int] = {}
        self._request_colors: Dict[RegionCoord, RgbColor] = {}
        self._token = 0
        self._dirty = True
        self._rendering = False
        self._blocked_spec: Optional[MapSurfaceSpec] = None
        self._visible_regions: set[RegionCoord] = set()
        self._covers_viewport = False
        self._latest_visible_bounds: Optional[RegionBounds] = None
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0

        self.enabled = False
        self.image: Optional[object] = None
        self.control: Optional[ft.Container] = None
        self._init_raw_image(background_color)

    def _init_raw_image(self, background_color: str) -> None:
        if not hasattr(ft, "RawImage"):
            return
        try:
            self.image = ft.RawImage(
                fit=ft.BoxFit.FILL,
                # The whole buffered surface is one image, so linear
                # filtering can preserve coastlines while shrinking LODs
                # without reopening the old per-tile seam problem.
                filter_quality=ft.FilterQuality.MEDIUM,
                ready_timeout=3.0,
                ack_timeout=8.0,
                expand=True,
            )
            self.control = ft.Container(
                content=self.image,
                left=0,
                top=0,
                width=1,
                height=1,
                padding=0,
                bgcolor=background_color,
                visible=False,
            )
            self.enabled = True
        except Exception:
            # Optional Flet RawImage may be unavailable or fail construction.
            self.enabled = False
            self.image = None
            self.control = None

    @property
    def frame(self) -> Optional[MapSurfaceFrame]:
        """当前已上传的表面帧；尚未合成时为 None。"""
        return self._frame

    @property
    def spec(self) -> Optional[MapSurfaceSpec]:
        """当前活跃表面规格。"""
        return self._spec

    @property
    def visible_regions(self) -> set[RegionCoord]:
        """本表面覆盖的区域坐标副本。"""
        return set(self._visible_regions)

    @property
    def covers_viewport(self) -> bool:
        """当前已上传表面是否完整覆盖并匹配视口。"""
        return self._covers_viewport

    @property
    def rendering(self) -> bool:
        """后台合成循环是否正在运行。"""
        return self._rendering

    def mark_tile_ready(self, coord: RegionCoord) -> bool:
        """瓦片完成时，仅当与本表面相交才标脏。

        瓦片 revision 是解码缓存键的一部分，因此下次 compose 不能
        复用陈旧像素。避免在合成进行中从服务线程加 renderer 锁。

        Args:
            coord: 完成的区域坐标。

        Returns:
            已标脏为 True；与可见集无关时为 False。
        """
        if self._is_closed() or coord not in self._visible_regions:
            return False
        # Tile revision is part of the decoded-image cache key, so the next
        # compose cannot reuse stale pixels.  Avoid taking the renderer lock
        # from the service worker callback while a frame is being composed.
        self._dirty = True
        self._blocked_spec = None
        return True

    def mark_dirty(self) -> None:
        """强制下次 ``sync`` 重新排队合成。"""
        if self._is_closed():
            return
        self._dirty = True
        self._blocked_spec = None

    def suspend(self) -> None:
        """使在途帧失效，但保留已上传表面供临时重挂过渡。"""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._token += 1
            self._dirty = True
            self._request_spec = None
            self._request_data.clear()
            self._request_colors.clear()
            self._blocked_spec = None

    def clear(self) -> None:
        """丢弃旧世界帧，但不取消进行中的上传 ACK。

        通过递增 token 使过期上传结果在完成后被忽略。
        """
        self._token += 1
        self._dirty = True
        self._visible_regions.clear()
        self._request_data.clear()
        self._request_colors.clear()
        self._request_spec = None
        self._frame = None
        self._spec = None
        self._blocked_spec = None
        self._covers_viewport = False
        self._latest_visible_bounds = None
        self.hide()

    def close(self) -> None:
        """取消在途工作并释放解码图像；可重复调用。"""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            task = self._task
            compose_handle = self._compose_handle
            self._task = None
            self._compose_handle = None
        self.clear()
        self._rendering = False
        if compose_handle is not None:
            compose_handle.cancel()
        if task is not None and not task.done():
            task.cancel()
        if compose_handle is None:
            self._renderer.close()
        else:
            compose_handle.add_done_callback(
                lambda _completed: self._renderer.close()
            )

    def _is_closed(self) -> bool:
        """返回图层是否已进入最终关闭状态。"""
        with self._lifecycle_lock:
            return self._closed

    def hide(self) -> None:
        """隐藏表面宿主控件。"""
        host = self.control
        if host is not None and getattr(host, "visible", True):
            host.visible = False
            safe_update(host)

    def sync(
        self,
        viewport: McaViewport,
        *,
        width: float,
        height: float,
        data: Mapping[RegionCoord, int],
        display_mode: str,
        use_topview: bool,
        color_for_region: ColorProvider,
    ) -> list[RegionCoord]:
        """按最新视口复用或排队表面帧。

        Args:
            viewport: 当前地图视口。
            width: 视口像素宽。
            height: 视口像素高。
            data: 区域坐标 -> 文件大小等元数据。
            display_mode: 着色/显示模式。
            use_topview: 是否使用俯视瓦片。
            color_for_region: 区域着色回调。

        Returns:
            仍缺俯视瓦片的区域坐标列表；未启用时为空。
        """
        if self._is_closed() or not self.enabled:
            return []
        self._sync_viewport_geometry(viewport)
        if not data:
            self.clear()
            return []

        candidate, visible_bounds = self._surface_candidate(
            viewport, width, height, display_mode, use_topview
        )
        self._latest_visible_bounds = visible_bounds
        if not self._contains(candidate, visible_bounds):
            self._use_canvas_fallback()
            return []
        self._covers_viewport = self._frame_matches_viewport(
            candidate,
            visible_bounds,
        )
        reused = self._reuse_active_surface(data, candidate, visible_bounds)
        if reused is not None:
            return reused
        reused = self._reuse_pending_surface(data, candidate, visible_bounds)
        if reused is not None:
            return reused

        candidate = self._with_active_bounds(candidate, visible_bounds)

        surface_data, colors = self._payload(data, candidate, color_for_region)
        self._visible_regions = set(surface_data)
        if (
            self._blocked_spec is None
            or self._blocked_spec != candidate
            or self._dirty
        ):
            self._queue(candidate, surface_data, colors)
        if self._frame is not None:
            self._update_geometry(self._frame.spec)

        return self._missing_tiles(surface_data, candidate)

    def _use_canvas_fallback(self) -> None:
        """使裁剪候选失效，避免不完整表面遮住 Canvas。"""
        self._token += 1
        self._dirty = True
        self._covers_viewport = False
        self._request_spec = None
        self._request_data.clear()
        self._request_colors.clear()
        self._visible_regions.clear()
        self._blocked_spec = None
        self.hide()

    def _frame_matches_viewport(
        self,
        candidate: MapSurfaceSpec,
        visible_bounds: RegionBounds,
    ) -> bool:
        frame = self._frame
        if frame is None or not self._contains(frame.spec, visible_bounds):
            return False
        return self._same_surface_format(frame.spec, candidate)

    def _sync_viewport_geometry(self, viewport: McaViewport) -> None:
        self._scale = max(0.001, float(viewport.scale))
        self._offset_x = float(viewport.offset_x)
        self._offset_y = float(viewport.offset_y)

    def _surface_candidate(
        self,
        viewport: McaViewport,
        width: float,
        height: float,
        display_mode: str,
        use_topview: bool,
    ) -> Tuple[MapSurfaceSpec, RegionBounds]:
        visible_bounds = self._visible_bounds(viewport, width, height)
        pixels_per_region = self._fit_pixels_per_region(viewport.scale, visible_bounds)
        surface_bounds = self._surface_bounds(viewport, width, height, pixels_per_region)
        return (
            MapSurfaceSpec(
                min_region_x=surface_bounds[0],
                max_region_x=surface_bounds[1],
                min_region_z=surface_bounds[2],
                max_region_z=surface_bounds[3],
                pixels_per_region=pixels_per_region,
                display_mode=display_mode,
                use_topview=use_topview,
                source_generation=self._service.get_topview_generation(),
                data_revision=self._service.get_data_revision(),
            ),
            visible_bounds,
        )

    @staticmethod
    def _visible_bounds(viewport: McaViewport, width: float, height: float) -> RegionBounds:
        try:
            return viewport.visible_region_bounds(width, height, margin=0.0)
        except ValueError:
            return (0, 0, 0, 0)

    def _fit_pixels_per_region(self, scale: float, visible_bounds: RegionBounds) -> int:
        pixels_per_region = self._pixels_per_region(scale)
        visible_columns = visible_bounds[1] - visible_bounds[0] + 1
        visible_rows = visible_bounds[3] - visible_bounds[2] + 1
        visible_count = max(1, visible_columns * visible_rows)
        while pixels_per_region > 16 and (
            visible_count * pixels_per_region * pixels_per_region > self._max_pixels
        ):
            # Preserve complete viewport coverage on wide/high-DPI windows.
            # Higher-resolution source tiles remain cached and are reduced
            # into the frame instead of cropping the world rectangle.
            pixels_per_region //= 2
        return pixels_per_region

    def _reuse_active_surface(
        self,
        data: Mapping[RegionCoord, int],
        candidate: MapSurfaceSpec,
        visible_bounds: RegionBounds,
    ) -> Optional[list[RegionCoord]]:
        active_spec = self._frame.spec if self._frame else None
        if active_spec is None or self._dirty:
            return None
        if not self._signature_matches(active_spec, candidate):
            return None
        if not self._contains(active_spec, visible_bounds):
            return None
        self._update_geometry(active_spec)
        return self._set_visible_regions(data, active_spec)

    def _reuse_pending_surface(
        self,
        data: Mapping[RegionCoord, int],
        candidate: MapSurfaceSpec,
        visible_bounds: RegionBounds,
    ) -> Optional[list[RegionCoord]]:
        pending = self._request_spec
        if pending is None or self._dirty or not self._rendering:
            return None
        if not self._signature_matches(pending, candidate):
            return None
        if not self._contains(pending, visible_bounds):
            return None
        if self._frame is not None:
            self._update_geometry(self._frame.spec)
        return self._set_visible_regions(data, pending)

    def _set_visible_regions(
        self,
        data: Mapping[RegionCoord, int],
        spec: MapSurfaceSpec,
    ) -> list[RegionCoord]:
        surface_data = self._surface_data(data, spec)
        self._visible_regions = set(surface_data)
        return self._missing_tiles(surface_data, spec)

    def _with_active_bounds(
        self,
        candidate: MapSurfaceSpec,
        visible_bounds: RegionBounds,
    ) -> MapSurfaceSpec:
        active_spec = self._frame.spec if self._frame else None
        if active_spec is None or not self._contains(active_spec, visible_bounds):
            return candidate
        if not self._same_surface_format(active_spec, candidate):
            return candidate
        return replace(active_spec, data_revision=candidate.data_revision)

    @staticmethod
    def _same_surface_format(first: MapSurfaceSpec, second: MapSurfaceSpec) -> bool:
        """True when resolution/mode/source match (ignores data_revision)."""
        return (
            first.pixels_per_region == second.pixels_per_region
            and first.display_mode == second.display_mode
            and first.use_topview == second.use_topview
            and first.source_generation == second.source_generation
        )

    def _pixels_per_region(self, scale: float) -> int:
        ladder = (
            HIGH_DETAIL_TILE_LADDER
            if scale >= 8.0
            else HIGH_DETAIL_TILE_LADDER[:-1]
        )
        return int(
            choose_tile_size(
                self._cell_size
                * max(scale, 0.01)
                * self.SOURCE_OVERSAMPLE,
                ladder,
            )
        )

    def _surface_bounds(
        self,
        viewport: McaViewport,
        width: float,
        height: float,
        pixels_per_region: int,
    ) -> Tuple[int, int, int, int]:
        # A 512px region already covers a large portion of the viewport.  Do
        # not surround it with two off-screen rings of equally expensive leaf
        # tiles; the currently visible regions are enough at this zoom.
        buffer_regions = 0 if pixels_per_region >= 512 else self._buffer_regions
        margin = viewport.cell_pitch * buffer_regions
        try:
            min_x, max_x, min_z, max_z = viewport.visible_region_bounds(
                width,
                height,
                margin=margin,
            )
        except ValueError:
            return (0, 0, 0, 0)
        try:
            center_x, center_z = viewport.nearest_region_at_screen(
                width / 2.0,
                height / 2.0,
            )
        except ValueError:
            center_x, center_z = (0, 0)
        min_x, max_x = self._clamp_axis(
            min_x,
            max_x,
            self._max_regions,
            center_x,
        )
        min_z, max_z = self._clamp_axis(
            min_z,
            max_z,
            self._max_regions,
            center_z,
        )
        return self._shrink_bounds_to_pixel_budget(
            min_x,
            max_x,
            min_z,
            max_z,
            center_x,
            center_z,
            pixels_per_region,
        )

    def _shrink_bounds_to_pixel_budget(
        self,
        min_x: int,
        max_x: int,
        min_z: int,
        max_z: int,
        center_x: int,
        center_z: int,
        pixels_per_region: int,
    ) -> Tuple[int, int, int, int]:
        while (
            (max_x - min_x + 1)
            * (max_z - min_z + 1)
            * pixels_per_region
            * pixels_per_region
            > self._max_pixels
        ):
            span_x = max_x - min_x + 1
            span_z = max_z - min_z + 1
            if span_x >= span_z and span_x > 1:
                if center_x - min_x >= max_x - center_x:
                    min_x += 1
                else:
                    max_x -= 1
            elif span_z > 1:
                if center_z - min_z >= max_z - center_z:
                    min_z += 1
                else:
                    max_z -= 1
            else:
                break
        return min_x, max_x, min_z, max_z

    @staticmethod
    def _clamp_axis(low: int, high: int, limit: int, center: int) -> Tuple[int, int]:
        if high - low + 1 <= limit:
            return low, high
        low = center - limit // 2
        return low, low + limit - 1

    @staticmethod
    def _contains(
        outer: MapSurfaceSpec,
        inner: Tuple[int, int, int, int],
    ) -> bool:
        min_x, max_x, min_z, max_z = inner
        return (
            outer.min_region_x <= min_x
            and outer.max_region_x >= max_x
            and outer.min_region_z <= min_z
            and outer.max_region_z >= max_z
        )

    @staticmethod
    def _signature_matches(first: MapSurfaceSpec, second: MapSurfaceSpec) -> bool:
        return (
            MapSurfaceLayer._same_surface_format(first, second)
            and first.data_revision == second.data_revision
        )

    def _payload(
        self,
        data: Mapping[RegionCoord, int],
        spec: MapSurfaceSpec,
        color_for_region: ColorProvider,
    ) -> Tuple[Dict[RegionCoord, int], Dict[RegionCoord, RgbColor]]:
        surface_data = self._surface_data(data, spec)
        colors = {
            coord: _rgb(color_for_region(coord, size))
            for coord, size in surface_data.items()
        }
        return surface_data, colors

    def _surface_data(
        self,
        data: Mapping[RegionCoord, int],
        spec: MapSurfaceSpec,
    ) -> Dict[RegionCoord, int]:
        """Return present regions covered by a buffered surface spec."""
        surface_data: Dict[RegionCoord, int] = {}
        for region_z in range(spec.min_region_z, spec.max_region_z + 1):
            for region_x in range(spec.min_region_x, spec.max_region_x + 1):
                coord = (region_x, region_z)
                size = data.get(coord)
                if size is not None:
                    surface_data[coord] = size
        return surface_data

    def _missing_tiles(
        self,
        surface_data: Mapping[RegionCoord, int],
        spec: MapSurfaceSpec,
    ) -> list[RegionCoord]:
        if not spec.use_topview:
            return []
        required_size = min(spec.pixels_per_region, ULTRA_TILE_SIZE)
        return [
            coord
            for coord in surface_data
            if not self._service.has_topview_tile(
                coord,
                min_size=required_size,
            )
        ]

    def _queue(
        self,
        spec: MapSurfaceSpec,
        data: Mapping[RegionCoord, int],
        colors: Mapping[RegionCoord, RgbColor],
    ) -> None:
        if self._is_closed():
            return
        self._request_spec = spec
        self._request_data = dict(data)
        self._request_colors = dict(colors)
        self._token += 1
        self._blocked_spec = None
        if not self._is_active() or self.image is None:
            self._dirty = True
            return
        self._dirty = False
        if self._rendering:
            return
        self._rendering = True
        task = self._schedule_task(self._render_loop())
        if task is None:
            self._rendering = False
            return
        with self._lifecycle_lock:
            if self._closed:
                task.cancel()
                self._rendering = False
                return
            self._task = task

    async def _render_loop(self) -> None:
        try:
            while self._can_render() and self.image is not None:
                request = self._capture_request()
                if request is None:
                    break
                if await self._render_request(request):
                    continue
                break
        finally:
            self._rendering = False
            with self._lifecycle_lock:
                self._task = None
            if self._can_render() and self._dirty:
                self._request_rebuild()

    def _can_render(self) -> bool:
        """仅允许仍存活且挂载的图层执行或发布表面。"""
        return self.enabled and not self._is_closed() and self._is_active()

    async def _render_request(self, request: _RenderRequest) -> bool:
        """Render one request and report whether a newer request should retry."""
        frame = await self._compose_request(request)
        if frame is None:
            return not self._request_token_matches(request)
        if not self._request_token_matches(request):
            return True
        if not self._source_is_current(request.spec):
            self._invalidate_current_request()
            return False
        if not await self._upload_frame(request, frame):
            return not self._request_token_matches(request)
        if not self._request_is_current(request):
            return True
        self._store_frame(request, frame)
        return False

    def _request_token_matches(self, request: _RenderRequest) -> bool:
        return request.token == self._token

    def _request_is_current(self, request: _RenderRequest) -> bool:
        return self._request_token_matches(request) and self._can_render()

    def _store_frame(self, request: _RenderRequest, frame: MapSurfaceFrame) -> None:
        was_ready = self._covers_viewport
        self._frame = frame
        self._spec = request.spec
        self._dirty = False
        self._blocked_spec = None
        visible_bounds = self._latest_visible_bounds
        self._covers_viewport = (
            visible_bounds is not None
            and self._contains(request.spec, visible_bounds)
        )
        self._update_geometry(request.spec)
        if self._covers_viewport and not was_ready and self._on_ready is not None:
            self._on_ready()

    def _capture_request(self) -> Optional[_RenderRequest]:
        spec = self._request_spec
        if spec is None:
            return None
        data = dict(self._request_data)
        coords = list(data) if spec.use_topview else []
        snapshot_generation, tile_bytes, tile_revisions = (
            self._service.get_topview_snapshot(coords)
        )
        if snapshot_generation != spec.source_generation:
            spec = replace(spec, source_generation=snapshot_generation)
            self._request_spec = spec
        if self._service.get_data_revision() != spec.data_revision:
            self._invalidate_current_request()
            return None
        return _RenderRequest(
            spec=spec,
            data=data,
            colors=dict(self._request_colors),
            token=self._token,
            tile_bytes=tile_bytes,
            tile_revisions=tile_revisions,
        )

    async def _compose_request(
        self,
        request: _RenderRequest,
    ) -> Optional[MapSurfaceFrame]:
        handle: Optional[OperationHandle[MapSurfaceFrame]] = None
        try:
            with self._lifecycle_lock:
                if self._closed:
                    return None
                handle = self._execution_runtime.submit(
                    "compose_map_surface",
                    lambda token: self._renderer.compose(
                        request.spec,
                        request.data,
                        request.tile_bytes,
                        request.tile_revisions,
                        request.colors,
                        cancel_check=lambda: (
                            token.is_cancelled
                            or not self._request_is_current(request)
                        ),
                    ),
                    lane=ExecutionLane.CPU,
                    priority=TaskPriority.VISIBLE,
                )
                self._compose_handle = handle
            return await handle.wait_async()
        except Exception:
            if self._request_token_matches(request):
                self._blocked_spec = request.spec
                self._dirty = False
            return None
        finally:
            if handle is not None:
                with self._lifecycle_lock:
                    if self._compose_handle is handle:
                        self._compose_handle = None

    def _source_is_current(self, spec: MapSurfaceSpec) -> bool:
        return (
            self._service.get_data_revision() == spec.data_revision
            and self._service.get_topview_generation() == spec.source_generation
        )

    def _invalidate_current_request(self) -> None:
        self._dirty = True
        self._request_rebuild()

    async def _upload_frame(
        self,
        request: _RenderRequest,
        frame: MapSurfaceFrame,
    ) -> bool:
        self._update_geometry(request.spec, update=False)
        self._show()
        try:
            await self.image.render_rgba(  # type: ignore[union-attr]
                frame.width,
                frame.height,
                frame.pixels,
                premultiplied=True,
            )
        except Exception as exc:
            self._disable_after_upload_failure(exc)
            return False
        # ``clear()`` may invalidate this frame while its ACK is pending.  Do
        # not resurrect pixels from the previous world or camera generation.
        return request.token == self._token and self._is_active()

    def _disable_after_upload_failure(self, error: Exception) -> None:
        """禁用失效的 RawImage 通道并通知宿主切换到 Canvas。"""
        with self._lifecycle_lock:
            if self._closed or not self.enabled:
                return
            self.enabled = False
            self._covers_viewport = False
            self._token += 1
            self._dirty = False
            self._request_spec = None
            self._request_data.clear()
            self._request_colors.clear()
            self._blocked_spec = None
        self.hide()
        logger.warning(
            "RawImage 地图表面上传失败，已回退到 Canvas: "
            f"{type(error).__name__}: {error}",
            module="McaMapSurface",
        )
        if self._on_unavailable is not None:
            self._on_unavailable(error)

    def _show(self) -> None:
        if self._is_closed():
            return
        host = self.control
        if host is not None and not getattr(host, "visible", True):
            host.visible = True
            safe_update(host)

    def _update_geometry(self, spec: MapSurfaceSpec, *, update: bool = True) -> None:
        host = self.control
        if host is None:
            return
        host.left = self._offset_x + spec.min_region_x * self._cell_size * self._scale
        host.top = self._offset_y + spec.min_region_z * self._cell_size * self._scale
        host.width = spec.columns * self._cell_size * self._scale
        host.height = spec.rows * self._cell_size * self._scale
        host.visible = True
        if update:
            safe_update(host)


__all__ = ["MapSurfaceLayer"]
