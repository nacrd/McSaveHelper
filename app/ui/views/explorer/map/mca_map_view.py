"""MCA region map view — minimal interactive map display.

Draws region files (r.x.z.mca) as a colored grid on Flet Canvas.
Supports pan, zoom, click-to-select, and progressive scan updates.

Zoom levels (auto-switched by scale thresholds on wheel):
  world  — overview of many regions
  region — one/few regions dominant
  chunk  — 32x32 chunk mesh inside a region
  block  — deep zoom into a single chunk (16x16 block mesh)
"""
from __future__ import annotations

import asyncio
import threading
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Coroutine,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    cast,
)

import flet as ft

try:
    import flet.canvas as cv
except ImportError as exc:  # pragma: no cover
    raise ImportError("flet.canvas is not available in this Flet version") from exc

from app.ui.delayed_scheduler import UiDelayedScheduler
from app.ui.utils import (
    ScheduledTask,
    run_on_ui,
    safe_update,
    schedule_coroutine,
)
from app.ui.views.explorer.map.color_schemes import (
    BACKGROUND_COLOR,
    EMPTY_REGION_COLOR,
    get_biome_color,
    get_region_color,
    get_region_value_label,
    get_structure_color,
)
from app.ui.views.explorer.map import map_shapes
from app.ui.views.explorer.map.map_hit_testing import hit_bounds
from app.ui.views.explorer.map.camera_animator import MapCameraAnimator
from app.ui.views.explorer.map.rebuild_scheduler import RebuildScheduler
from app.ui.views.explorer.map.tile_source_cache import TileSourceCache
from app.ui.views.explorer.map.marker_layer import MapMarkerLayer
from app.ui.views.explorer.map.map_surface_layer import MapSurfaceLayer
from app.controllers.topview_tile_requests import TopviewTileRequestCoordinator
from app.ui.views.explorer.map.map_tile_request_adapter import (
    adapt_viewport_tile_requests,
)
from app.ui.views.explorer.map.map_interaction_state import (
    snapshot_from_map_view,
)
from core.mca.map_coordinates import (
    format_region_coordinate_label,
)
from core.mca.map_models import MapLayerState, MapLayerStateSnapshot, MapMarker
from core.mca.map_navigation import (
    McaMapNavigator,
    SelectionNotification,
)
from core.mca.map_gestures import (
    MapGestureResult,
    decide_double_tap,
    decide_secondary_tap,
    decide_tap,
)
from core.mca.viewport import (
    MAX_SCALE,
    MIN_SCALE,
    MapViewLevel,
    McaMapSelection,
    SCALE_BLOCK,
    SCALE_CHUNK,
    SCALE_REGION,
    McaViewport,
    ViewportTarget,
    view_level_from_scale,
)

if TYPE_CHECKING:
    from app.services.cache_registry import CacheRegistry
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.region_map import RegionMapService


MapSelectionCallback = Callable[
    [Optional[Tuple[int, int]], Optional[int], Optional[Dict[str, Any]]], None
]
MapMarkerCallback = Callable[[MapMarker], None]


class McaMapView(ft.Container):
    """Minimal MCA region map (presence grid, not size heatmap)."""

    BACKGROUND_COLOR = BACKGROUND_COLOR
    EMPTY_REGION_COLOR = EMPTY_REGION_COLOR
    CELL_SIZE = 32
    CELL_GAP = 0
    SURFACE_BUFFER_REGIONS = 2
    SURFACE_MAX_REGIONS = 192

    MIN_SCALE = MIN_SCALE
    MAX_SCALE = MAX_SCALE
    SCALE_REGION = SCALE_REGION
    SCALE_CHUNK = SCALE_CHUNK
    SCALE_BLOCK = SCALE_BLOCK

    def __init__(
        self,
        map_service: RegionMapService,
        execution_runtime: Optional[ExecutionRuntime] = None,
        on_selection_changed: Optional[MapSelectionCallback] = None,
        on_marker_selected: Optional[MapMarkerCallback] = None,
        width: int = 700,
        height: int = 450,
        cache_registry: Optional[CacheRegistry] = None,
        **kwargs: Any,
    ) -> None:
        """构建地图控件并挂到共享的 RegionMapService。

        Args:
            map_service: 区域扫描/瓦片服务；由 Explorer 会话持有生命周期。
            execution_runtime: 应用级有界后台运行时。
            on_selection_changed: 区域/区块选择变化回调（UI 线程）。
            on_marker_selected: 标记被点中时的回调。
            width: 初始宽度像素。
            height: 初始高度像素。
            cache_registry: 应用级缓存预算；视图释放时自动注销。
            **kwargs: 透传给 ``ft.Container``。
        """
        super().__init__(**kwargs)
        self._service = map_service
        self._execution_runtime = (
            execution_runtime or map_service.execution_runtime
        )
        self._on_selection_changed = on_selection_changed
        self._on_marker_selected = on_marker_selected
        try:
            self._init_viewport_state(cache_registry)
            self._init_interaction_state()
            self._init_layers_and_content(width, height)
        except Exception:
            # 可选 Flet/canvas 边界可能在预算登记后失败，必须归还视图缓存预算。
            tile_sources = getattr(self, "_tile_sources", None)
            if tile_sources is not None:
                tile_sources.close()
            raise

    def _init_viewport_state(
        self,
        cache_registry: Optional[CacheRegistry],
    ) -> None:
        """Viewport, selection, and static map display flags."""
        self._viewport = McaViewport(
            cell_size=float(self.CELL_SIZE),
            cell_gap=float(self.CELL_GAP),
            min_scale=self.MIN_SCALE,
            max_scale=self.MAX_SCALE,
        )
        self._show_coordinates = False
        self._show_grid = False
        self._show_empty_regions = False
        self._display_mode = "topview"
        self._detail_level = "region"
        self._use_topview = True

        self._selection = McaMapSelection()
        self._navigator = McaMapNavigator(self._selection)
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[
            Tuple[int, int], Tuple[float, float, float, float]
        ] = {}
        self._chunk_bounds: Dict[
            Tuple[int, int], Tuple[float, float, float, float]
        ] = {}
        self._block_bounds: Dict[
            Tuple[int, int], Tuple[float, float, float, float]
        ] = {}
        self._cached_stats: Optional[Dict[str, Any]] = None
        self._tile_sources = TileSourceCache(cache_registry)
        self._metadata_pending: set[Tuple[int, int]] = set()
        self._marker_layer = MapMarkerLayer()
        self._tile_ready_callback = self._on_tile_ready
        self._tile_requests = TopviewTileRequestCoordinator(self._service)

    def _init_interaction_state(self) -> None:
        """Pointer tracking, camera, and rebuild scheduling."""
        self._last_x = 0.0
        self._last_y = 0.0
        self._needs_initial_draw = True
        self._update_task: Optional[ScheduledTask] = None
        self._last_drawn_count = -1
        self._mounted = False
        self._disposed = False
        self._visible_regions: set[Tuple[int, int]] = set()
        self._rebuild_state_lock = threading.Lock()
        self._rebuild_enqueued = False
        self._rebuild_dirty = False
        self._delay_scheduler = UiDelayedScheduler(
            lambda: cast(Optional[ft.Page], self.page),
        )

        # Pointer used for level auto-switch while zooming.
        self._zoom_pivot_x = 0.0
        self._zoom_pivot_y = 0.0
        self._last_notified_level: Optional[str] = None
        self._camera = MapCameraAnimator(
            self._viewport,
            min_scale=self.MIN_SCALE,
            max_scale=self.MAX_SCALE,
            on_frame=self._on_camera_frame,
            on_complete=self._on_camera_complete,
            is_alive=lambda: self._mounted,
            schedule=self._delay_scheduler,
        )
        self._rebuild_scheduler = RebuildScheduler(
            self._request_rebuild,
            is_active=lambda: self._mounted,
            schedule_delayed=self._delay_scheduler,
            min_interval=1.0 / 30.0,
        )

    def _init_layers_and_content(self, width: int, height: int) -> None:
        """Surface/canvas/gesture stack and host geometry."""
        self.width = width
        self.height = height
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 0
        self.expand = True

        self._surface_layer = MapSurfaceLayer(
            self._service,
            execution_runtime=self._execution_runtime,
            schedule_task=self._schedule_task,
            request_rebuild=self._request_rebuild,
            is_active=self._surface_is_active,
            background_color=self.BACKGROUND_COLOR,
            on_ready=self._on_surface_ready,
            on_unavailable=self._on_surface_unavailable,
            cell_size=self.CELL_SIZE,
            buffer_regions=self.SURFACE_BUFFER_REGIONS,
            max_regions=self.SURFACE_MAX_REGIONS,
        )
        # RawImage presence only means the transport can be attempted.  Keep
        # Canvas active until the client acknowledges the first uploaded frame.
        self._surface_enabled = False
        self._surface_host = self._surface_layer.control
        self._surface_image = self._surface_layer.image

        self._canvas = cv.Canvas(
            expand=True,
            shapes=[] if self._surface_enabled else self._empty_shapes(),
            resize_interval=50,
            on_resize=self._on_canvas_resize,
        )
        self._gesture = ft.GestureDetector(
            on_pan_start=self._on_pan_start,
            on_pan_update=self._on_pan_update,
            on_tap=self._on_tap,
            on_double_tap=self._on_double_tap,
            on_secondary_tap=self._on_secondary_tap,
            on_scroll=self._on_scroll,
            expand=True,
        )
        layers: List[ft.Control] = []
        if self._surface_host is not None:
            layers.append(self._surface_host)
        layers.extend([self._canvas, self._gesture])
        self.content = ft.Stack(
            layers,
            expand=True,
            fit=ft.StackFit.EXPAND,
        )

    def _on_surface_ready(self) -> None:
        """首次表面帧就绪后再让 RawImage 接管底图。"""
        if (
            self._disposed
            or not self._surface_layer.enabled
            or not self._surface_layer.covers_viewport
        ):
            return
        self._surface_enabled = True
        self._request_rebuild()

    def _on_surface_unavailable(self, _error: Exception) -> None:
        """RawImage 通道失效后切换到稳定的 Canvas 底图。"""
        if self._disposed:
            return
        self._surface_enabled = False
        self._request_rebuild()

    @property
    def _scale(self) -> float:
        return self._viewport.scale

    @_scale.setter
    def _scale(self, value: float) -> None:
        self._viewport.scale = float(value)

    @property
    def _offset_x(self) -> float:
        return self._viewport.offset_x

    @_offset_x.setter
    def _offset_x(self, value: float) -> None:
        self._viewport.offset_x = float(value)

    @property
    def _offset_y(self) -> float:
        return self._viewport.offset_y

    @_offset_y.setter
    def _offset_y(self, value: float) -> None:
        self._viewport.offset_y = float(value)

    @property
    def _selected_cell(self) -> Optional[Tuple[int, int]]:
        return self._selection.region

    @_selected_cell.setter
    def _selected_cell(self, value: Optional[Tuple[int, int]]) -> None:
        self._selection.region = value
        if value is None:
            self._selection.chunk = None

    @property
    def _selected_chunk(self) -> Optional[Tuple[int, int]]:
        return self._selection.chunk

    @_selected_chunk.setter
    def _selected_chunk(self, value: Optional[Tuple[int, int]]) -> None:
        self._selection.chunk = value
        if value is not None:
            self._selection.region = (value[0] // 32, value[1] // 32)

    @property
    def _view_level(self) -> MapViewLevel:
        return self._selection.level

    @_view_level.setter
    def _view_level(self, value: MapViewLevel) -> None:
        self._selection.set_level(value)

    def _on_tile_ready(self, coord: Tuple[int, int]) -> None:
        """Called from a worker thread when a topview PNG is cached."""
        try:
            retry_deferred = self._tile_requests.on_tile_ready(coord)
            # A completed tile outside the buffered surface cannot affect the
            # current frame.  If a bounded queue previously rejected visible
            # work, however, any completion may free a slot for a retry.
            if self._surface_enabled:
                if coord not in self._visible_regions:
                    if retry_deferred:
                        self._rebuild_scheduler.schedule()
                    return
                if not self._surface_layer.mark_tile_ready(coord):
                    if retry_deferred:
                        self._rebuild_scheduler.schedule()
                    return
            elif self._current_data and coord not in self._current_data:
                if retry_deferred:
                    self._rebuild_scheduler.schedule()
                return
            self._rebuild_scheduler.schedule()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _tile_src(self, coord: Tuple[int, int]) -> Optional[str]:
        """Return base64 PNG for coord, caching decoded form for canvas."""
        return self._tile_sources.get(
            coord,
            generation=self._service.get_topview_generation(),
            version=self._service.get_topview_tile_revision(coord),
            load_tile=self._service.get_topview_tile,
        )

    # ------------------------------------------------------------------ UI helpers
    def _empty_shapes(self) -> List[cv.Shape]:
        return map_shapes.empty_background(
            self.width or 800,
            self.height or 600,
            self.BACKGROUND_COLOR,
        )

    def _request_rebuild(self) -> None:
        """Marshal canvas rebuild onto the Flet UI thread.

        Canvas.shapes must only be mutated on the UI thread. Background timers,
        topview workers, and off-loop scan tasks all funnel through here.
        """
        if self._disposed:
            return
        if not self._mounted:
            self._needs_initial_draw = True
            return
        try:
            page = self.page
        except RuntimeError:
            self._needs_initial_draw = True
            return
        if page is None:
            self._needs_initial_draw = True
            return
        with self._rebuild_state_lock:
            if self._rebuild_enqueued:
                self._rebuild_dirty = True
                return
            self._rebuild_enqueued = True
        run_on_ui(cast(ft.Page, page), self._rebuild_canvas_safe)

    def _rebuild_canvas_safe(self) -> None:
        if not self._mounted or self.page is None:
            with self._rebuild_state_lock:
                self._rebuild_enqueued = False
                self._rebuild_dirty = False
            return
        schedule_tail = False
        try:
            self._rebuild_canvas()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        finally:
            with self._rebuild_state_lock:
                if self._rebuild_dirty and self._mounted and self.page is not None:
                    self._rebuild_dirty = False
                    schedule_tail = True
                else:
                    self._rebuild_enqueued = False
            if schedule_tail and self.page is not None:
                run_on_ui(cast(ft.Page, self.page), self._rebuild_canvas_safe)

    # ------------------------------------------------------------------ gestures
    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        dx = e.local_position.x - self._last_x
        dy = e.local_position.y - self._last_y
        self._viewport.pan(dx, dy)
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y
        self._rebuild_scheduler.schedule()

    def _on_tap(self, e: ft.TapEvent) -> None:
        local_position = e.local_position
        if local_position is None:
            return
        marker = self._marker_layer.hit_test(local_position.x, local_position.y)
        if marker is not None:
            if self._on_marker_selected is not None:
                self._on_marker_selected(marker)
            self._request_rebuild()
            return
        result = decide_tap(
            navigator=self._navigator,
            region_sizes=self._current_data,
            view_level=self._view_level,
            scale=self._scale,
            scale_block=self.SCALE_BLOCK,
            hit_chunk=self._hit_chunk(local_position.x, local_position.y),
            hit_region=self._hit_region(local_position.x, local_position.y),
        )
        self._apply_gesture_result(result)

    def _on_double_tap(self, e: Any) -> None:
        """Double-click: zoom to chunk level, or deeper into a single chunk."""
        tap_x = getattr(getattr(e, "local_position", None), "x", None)
        tap_y = getattr(getattr(e, "local_position", None), "y", None)
        if tap_x is None or tap_y is None:
            tap_x = getattr(e, "local_x", (self.width or 800) / 2)
            tap_y = getattr(e, "local_y", (self.height or 600) / 2)
        result = decide_double_tap(
            navigator=self._navigator,
            region_sizes=self._current_data,
            view_level=self._view_level,
            hit_chunk=self._hit_chunk(float(tap_x), float(tap_y)),
            hit_region=self._hit_region(float(tap_x), float(tap_y)),
            selected_region=self._selected_cell,
        )
        self._apply_gesture_result(result)

    def _on_secondary_tap(self, e: Any) -> None:
        """Right-click: step back overview (block→chunk→region→world)."""
        result = decide_secondary_tap(
            navigator=self._navigator,
            region_sizes=self._current_data,
            previous_level=self._view_level,
            selected_region=self._selected_cell,
        )
        self._apply_gesture_result(result)

    def _apply_gesture_result(self, result: Optional[MapGestureResult]) -> None:
        if result is None:
            return
        if result.notification is not None:
            self._emit_selection(result.notification)
        if result.focus_chunk is not None:
            self._focus_chunk(
                result.focus_chunk,
                animate=True,
                target_fill=result.focus_fill,
            )
        elif result.focus_region is not None:
            self._focus_region(
                result.focus_region,
                animate=True,
                target_fill=result.focus_fill,
            )
        if result.set_level is not None:
            self._view_level = result.set_level
        if result.request_detail is not None and self._use_topview:
            self._request_detail_tiles(
                [result.request_detail],
                force=True,
                priority=True,
            )
        if result.fit_to_view:
            self.fit_to_view(padding=result.fit_padding)
        if result.rebuild:
            self._request_rebuild()

    def _hit_region(self, tap_x: float, tap_y: float) -> Optional[Tuple[int, int]]:
        try:
            return self._viewport.region_at_screen(
                tap_x,
                tap_y,
                self._current_data,
            )
        except (TypeError, ValueError):
            return hit_bounds(
                tap_x,
                tap_y,
                self._cell_bounds,
                allowed=self._current_data,
            )

    def _hit_chunk(self, tap_x: float, tap_y: float) -> Optional[Tuple[int, int]]:
        try:
            return self._viewport.chunk_at_screen(
                tap_x,
                tap_y,
                self._current_data,
            )
        except (TypeError, ValueError):
            return hit_bounds(tap_x, tap_y, self._chunk_bounds)

    def _coord_label_for_region(self, coord: Tuple[int, int], cell_size: float) -> str:
        return format_region_coordinate_label(
            coord,
            view_level=self._view_level,
            scale=self._scale,
            cell_size=cell_size,
        )

    def _focus_region(
        self,
        coord: Tuple[int, int],
        *,
        animate: bool = True,
        target_fill: float = 0.72,
    ) -> None:
        """Center and zoom so the given region fills most of the viewport."""
        view_w = float(self.width or 800)
        view_h = float(self.height or 600)
        if view_w <= 1 or view_h <= 1:
            self._request_rebuild()
            return

        target = self._viewport.focus_region(
            coord,
            view_w,
            view_h,
            target_fill,
        )

        # Prefer detail tiles for the focused region and its neighbors.
        if self._use_topview:
            self._tile_requests.request_region_detail(coord, self._current_data)

        self._apply_camera_target(target, animate=animate)

    def _focus_chunk(
        self,
        chunk_coord: Tuple[int, int],
        *,
        animate: bool = True,
        target_fill: float = 0.78,
    ) -> None:
        """Center and zoom so a single 16x16 chunk fills most of the viewport."""
        view_w = float(self.width or 800)
        view_h = float(self.height or 600)
        if view_w <= 1 or view_h <= 1:
            self._request_rebuild()
            return

        cx, cz = chunk_coord
        rx = cx // 32
        rz = cz // 32
        target = self._viewport.focus_chunk(
            chunk_coord,
            view_w,
            view_h,
            target_fill,
        )

        self._selected_cell = (rx, rz)
        self._selected_chunk = chunk_coord

        if self._use_topview:
            self._request_detail_tiles([(rx, rz)], force=True, priority=True)

        self._apply_camera_target(target, animate=animate)

    def _apply_camera_target(
        self,
        target: ViewportTarget,
        *,
        animate: bool,
        duration: float = 0.28,
        sync_view_level: bool = False,
    ) -> None:
        if animate:
            self._camera.animate_to(
                target.scale,
                target.offset_x,
                target.offset_y,
                duration=duration,
            )
            return
        self._viewport.apply(target)
        if sync_view_level:
            self._sync_view_level_from_scale(notify=True)
        self._request_rebuild()

    def _on_scroll(self, e: ft.ScrollEvent) -> None:
        scroll_delta = getattr(e, "scroll_delta", None)
        delta_y = (
            getattr(scroll_delta, "y", 0)
            if scroll_delta is not None
            else getattr(e, "delta_y", 0)
        )
        if not delta_y:
            return
        zoom_factor = 1.12 if delta_y < 0 else 0.89
        pointer_x = getattr(
            getattr(e, "local_position", None),
            "x",
            (self.width or 800) / 2,
        )
        pointer_y = getattr(
            getattr(e, "local_position", None),
            "y",
            (self.height or 600) / 2,
        )
        self._zoom_pivot_x = float(pointer_x)
        self._zoom_pivot_y = float(pointer_y)
        self._camera.animate_zoom_about(zoom_factor, float(pointer_x), float(pointer_y))

    def _sync_view_level_from_scale(
        self,
        *,
        pivot_x: Optional[float] = None,
        pivot_y: Optional[float] = None,
        notify: bool = True,
    ) -> bool:
        """Update ``_view_level`` from current scale thresholds.

        On zoom-in crossings, auto-select the region/chunk under the pivot so the
        side panel stays in sync without requiring an extra click. Returns True
        when the semantic level changed.
        """
        px = self._zoom_pivot_x if pivot_x is None else float(pivot_x)
        py = self._zoom_pivot_y if pivot_y is None else float(pivot_y)
        if px == 0.0 and py == 0.0:
            px = float(self.width or 800) / 2.0
            py = float(self.height or 600) / 2.0

        new_level = view_level_from_scale(self._scale)
        transition = self._navigator.transition_to(new_level)

        if not transition.changed:
            if new_level in {"chunk", "block"}:
                self._auto_select_under_pointer(px, py, new_level, notify=False)
            return False

        if transition.going_deeper or new_level in {"chunk", "block"}:
            self._auto_select_under_pointer(px, py, new_level, notify=False)
            if self._use_topview and self._selected_cell is not None:
                self._request_detail_tiles(
                    [self._selected_cell],
                    force=True,
                    priority=True,
                )

        if notify and (
            transition.changed or new_level != self._last_notified_level
        ):
            self._notify_level_selection(new_level)
        return True

    def _auto_select_under_pointer(
        self,
        px: float,
        py: float,
        level: str,
        *,
        notify: bool = False,
    ) -> None:
        """Pick region/chunk under screen point for the given level."""
        region = self._hit_region(px, py)
        if region is None and self._selected_cell is not None:
            region = self._selected_cell
        if region is None:
            region = self._region_at_screen(px, py)

        if region is not None and region in self._current_data:
            self._selected_cell = region

        if level in {"chunk", "block"}:
            chunk = self._hit_chunk(px, py)
            if chunk is None:
                chunk = self._chunk_at_screen(px, py)
            if chunk is not None:
                self._selected_chunk = chunk
                self._selected_cell = (chunk[0] // 32, chunk[1] // 32)
        else:
            self._selected_chunk = None

        if notify:
            self._notify_level_selection(level)

    def _region_at_screen(self, px: float, py: float) -> Optional[Tuple[int, int]]:
        """Inverse-project screen point → region coord (no hit-test needed)."""
        return self._viewport.region_at_screen(px, py, self._current_data)

    def _chunk_at_screen(self, px: float, py: float) -> Optional[Tuple[int, int]]:
        """Inverse-project screen point → world chunk coord."""
        return self._viewport.chunk_at_screen(px, py, self._current_data)

    def _notify_level_selection(self, level: str) -> None:
        self._last_notified_level = level
        notification = self._navigator.current_notification(
            self._current_data,
            cast(MapViewLevel, level),
        )
        self._emit_selection(notification)

    def _emit_selection(self, notification: SelectionNotification) -> None:
        if self._on_selection_changed:
            self._on_selection_changed(
                notification.region,
                notification.size,
                notification.detail,
            )

    # ------------------------------------------------------------------ draw
    def _rebuild_canvas(self) -> None:
        self._current_data = self._service.get_all_data()
        self._cached_stats = self._service.get_statistics()
        view_w = float(self.width or 800)
        view_h = float(self.height or 600)

        if not self._current_data:
            self._visible_regions.clear()
            self._tile_requests.reset()
            self._surface_layer.clear()
            self._surface_enabled = False
            shapes = list(self._empty_shapes())
            shapes.extend(map_shapes.empty_state(view_w, view_h))
            shapes.extend(self._build_info_overlay())
            self._apply_shapes(shapes)
            return

        coords = list(self._current_data.keys())
        self._cell_bounds.clear()
        self._chunk_bounds.clear()
        self._block_bounds.clear()

        draw_bounds = self._prepare_visible_bounds(coords, view_w, view_h)
        if draw_bounds is None:
            self._apply_shapes(list(self._empty_shapes()))
            return

        surface_missing: List[Tuple[int, int]] = []
        if self._surface_layer.enabled:
            surface_missing = self._prepare_surface(view_w, view_h)
        self._surface_enabled = (
            self._surface_layer.enabled
            and self._surface_layer.frame is not None
            and self._surface_layer.covers_viewport
        )
        # RawImage owns the opaque base layer only after a complete frame is
        # ready.  Cropped or pending surfaces leave the Canvas background on.
        shapes: List[cv.Shape] = (
            [] if self._surface_enabled else list(self._empty_shapes())
        )
        if self._surface_enabled:
            missing = surface_missing
            shapes.extend(self._build_surface_overlays(view_w, view_h))
        else:
            region_shapes, missing = self._build_visible_regions(
                draw_bounds,
                view_w,
                view_h,
            )
            shapes.extend(region_shapes)
        shapes.extend(self._build_marker_overlay())
        self._request_visible_tiles(missing)
        self._request_selected_detail_tiles()

        shapes.extend(self._build_info_overlay())
        self._apply_shapes(shapes)
        self._needs_initial_draw = False

    def _region_fill_color(self, coord: Tuple[int, int], size: int) -> str:
        meta = self._service.get_region_meta(coord)
        if self._display_mode == "biome":
            return get_biome_color(str(meta.get("dominant_biome", "unknown")))
        if self._display_mode == "structure":
            return get_structure_color(
                int(meta.get("structure_count", 0) or 0),
                str(meta.get("dominant_structure", "none")),
            )
        return get_region_color(size, self._cached_stats or {})

    def _surface_is_active(self) -> bool:
        try:
            return self._mounted and self.page is not None
        except RuntimeError:
            return False

    def _prepare_surface(self, view_w: float, view_h: float) -> List[Tuple[int, int]]:
        layer = self._surface_layer
        missing = layer.sync(
            self._viewport,
            width=view_w,
            height=view_h,
            data=self._current_data,
            display_mode=self._display_mode,
            use_topview=self._use_topview,
            color_for_region=self._region_fill_color,
        )
        self._visible_regions = layer.visible_regions
        self._record_cell_bounds(view_w, view_h)
        self._request_visible_metadata_for_surface(self._visible_regions)
        return missing

    def _record_cell_bounds(self, view_w: float, view_h: float) -> None:
        self._cell_bounds.clear()
        if self._mounted and not self._show_coordinates:
            selected = self._selected_cell
            if selected is not None and selected in self._visible_regions:
                rect = self._viewport.region_rect(selected)
                if not self._rect_outside_view(rect, view_w, view_h):
                    self._cell_bounds[selected] = rect
            return
        for coord in self._visible_regions:
            rect = self._viewport.region_rect(coord)
            if not self._rect_outside_view(rect, view_w, view_h):
                self._cell_bounds[coord] = rect

    def _request_visible_metadata_for_surface(
        self,
        coords: Iterable[Tuple[int, int]],
    ) -> None:
        if self._display_mode not in {"biome", "structure"}:
            return
        missing = [
            coord
            for coord in coords
            if coord in self._current_data
            and not self._service.get_region_meta(coord)
        ]
        self._request_visible_metadata(missing)

    def _build_surface_overlays(
        self,
        view_w: float,
        view_h: float,
    ) -> List[cv.Shape]:
        del view_w, view_h
        shapes: List[cv.Shape] = []
        selected = self._selected_cell
        if selected is not None and selected in self._current_data:
            x, y, width, height = self._viewport.region_rect(selected)
            shapes.append(
                cv.Rect(
                    x,
                    y,
                    width,
                    height,
                    paint=ft.Paint(
                        color="#FFD54F",
                        style=ft.PaintingStyle.STROKE,
                        stroke_width=3,
                    ),
                )
            )
            if self._show_coordinates and width >= 22:
                shapes.append(
                    cv.Text(
                        x=x + 4,
                        y=y + 5,
                        value=self._coord_label_for_region(selected, width),
                        style=ft.TextStyle(size=10, color="#FFFFFF"),
                    )
                )
            if self._show_grid:
                shapes.extend(
                    self._build_chunk_grid(
                        x,
                        y,
                        width,
                        selected,
                        show_block_grid=self._view_level == "block",
                    )
                )

        if self._show_coordinates:
            for coord, (x, y, width, _height) in self._cell_bounds.items():
                if coord == selected or width < 22:
                    continue
                shapes.append(
                    cv.Text(
                        x=x + 4,
                        y=y + 5,
                        value=self._coord_label_for_region(coord, width),
                        style=ft.TextStyle(
                            size=9 if width < 70 else 10,
                            color="#FFFFFF",
                        ),
                    )
                )
        return shapes

    def _prepare_visible_bounds(
        self,
        coords: List[Tuple[int, int]],
        view_w: float,
        view_h: float,
    ) -> Optional[Tuple[int, int, int, int]]:
        if self._viewport.is_default:
            target = self._viewport.fit(
                coords,
                view_w,
                view_h,
                padding=0.78,
                min_fit_scale=self.MIN_SCALE,
                max_fit_scale=3.0,
            )
            self._viewport.apply(target)
            self._view_level = view_level_from_scale(self._scale)
        try:
            visible = self._viewport.visible_region_bounds(view_w, view_h)
        except ValueError:
            return None
        min_x = min(coord[0] for coord in coords)
        max_x = max(coord[0] for coord in coords)
        min_z = min(coord[1] for coord in coords)
        max_z = max(coord[1] for coord in coords)
        return (
            max(min_x, visible[0]),
            min(max_x, visible[1]),
            max(min_z, visible[2]),
            min(max_z, visible[3]),
        )

    def _build_visible_regions(
        self,
        bounds: Tuple[int, int, int, int],
        view_w: float,
        view_h: float,
    ) -> Tuple[List[cv.Shape], List[Tuple[int, int]]]:
        shapes: List[cv.Shape] = []
        missing: List[Tuple[int, int]] = []
        metadata_missing: List[Tuple[int, int]] = []
        self._visible_regions.clear()
        show_chunk_grid = self._show_grid and (
            self._view_level in {"chunk", "block"}
            or self._scale >= self.SCALE_CHUNK
        )
        show_block_grid = self._show_grid and (
            self._view_level == "block" or self._scale >= self.SCALE_BLOCK
        )
        desired_tile_size = self._tile_requests.visible_base_tile_size(
            self._scale,
        )
        for coord in self._draw_coords(bounds):
            rect = self._viewport.region_rect(coord)
            if self._rect_outside_view(rect, view_w, view_h):
                continue
            self._cell_bounds[coord] = rect
            if coord in self._current_data:
                self._visible_regions.add(coord)
                if (
                    self._display_mode in {"biome", "structure"}
                    and not self._service.get_region_meta(coord)
                ):
                    metadata_missing.append(coord)
                shapes.extend(self._build_present_region(
                    coord,
                    rect,
                    show_chunk_grid,
                    show_block_grid,
                ))
                if (
                    self._use_topview
                    and not self._service.has_topview_tile(
                        coord,
                        min_size=desired_tile_size,
                    )
                ):
                    missing.append(coord)
            elif self._show_empty_regions:
                shapes.append(
                    map_shapes.empty_region(rect, self.EMPTY_REGION_COLOR)
                )
        self._request_visible_metadata(metadata_missing)
        return shapes, missing

    def _draw_coords(
        self,
        bounds: Tuple[int, int, int, int],
    ) -> Iterable[Tuple[int, int]]:
        """按稳定顺序返回需要绘制的真实或空区域坐标。"""
        min_x, max_x, min_z, max_z = bounds
        if self._show_empty_regions:
            return (
                (x, z)
                for z in range(min_z, max_z + 1)
                for x in range(min_x, max_x + 1)
            )
        return (
            coord
            for coord in sorted(self._current_data)
            if min_x <= coord[0] <= max_x and min_z <= coord[1] <= max_z
        )

    @staticmethod
    def _rect_outside_view(
        rect: Tuple[float, float, float, float],
        view_w: float,
        view_h: float,
    ) -> bool:
        x, y, width, height = rect
        return x + width < 0 or x > view_w or y + height < 0 or y > view_h

    def _build_present_region(
        self,
        coord: Tuple[int, int],
        rect: Tuple[float, float, float, float],
        show_chunk_grid: bool,
        show_block_grid: bool,
    ) -> List[cv.Shape]:
        x, y, size, _ = rect
        file_size = self._current_data[coord]
        color = self._region_fill_color(coord, file_size)
        shapes = self._build_region_cell(x, y, size, color, coord, file_size)
        if show_chunk_grid:
            shapes.extend(self._build_chunk_grid(
                x,
                y,
                size,
                coord,
                show_block_grid=show_block_grid,
            ))
        return shapes

    def _request_visible_metadata(self, coords: List[Tuple[int, int]]) -> None:
        """Load visible biome/structure summaries without blocking the UI."""
        if not self._mounted:
            return
        pending = [
            coord
            for coord in coords
            if coord not in self._metadata_pending
        ]
        if not pending:
            return
        batch = adapt_viewport_tile_requests(
            pending,
            center=self._viewport_center_region(),
            preferred_tile_size=32,
            limit=24,
        )
        pending = list(batch.coords)
        self._interaction_snapshot = snapshot_from_map_view(self)
        self._metadata_pending.update(pending)
        self._schedule_task(self._load_visible_metadata(pending))

    async def _load_visible_metadata(
        self,
        coords: List[Tuple[int, int]],
    ) -> None:
        # Metadata sampling opens MCA files. The caller caps each batch so a
        # world overview cannot flood asyncio.to_thread with hundreds of jobs.
        try:
            for coord in coords:
                if not self._mounted:
                    break
                await self._service.ensure_region_meta(coord)
        except asyncio.CancelledError:
            raise
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        finally:
            for coord in coords:
                self._metadata_pending.discard(coord)
            self._surface_layer.mark_dirty()
            self._rebuild_scheduler.schedule()

    def _request_visible_tiles(self, missing: List[Tuple[int, int]]) -> None:
        if not self._mounted:
            self._tile_requests.reset()
            return
        self._tile_requests.request_visible(
            missing,
            visible_regions=self._visible_regions,
            scale=self._scale,
            center=self._viewport_center_region(),
        )

    def _viewport_center_region(self) -> Tuple[int, int]:
        """Return the region nearest the screen center, including empty space."""
        try:
            return self._viewport.nearest_region_at_screen(
                float(self.width or 800) / 2.0,
                float(self.height or 600) / 2.0,
            )
        except ValueError:
            return (0, 0)

    def _request_selected_detail_tiles(self) -> None:
        self._tile_requests.request_selected_detail(
            scale=self._scale,
            selected=self._selected_cell,
            center=self._viewport_center_region(),
            available_regions=self._current_data,
            enabled=self._use_topview,
        )

    def _request_detail_tiles(
        self,
        coords: List[Tuple[int, int]],
        *,
        tile_size: Optional[int] = None,
        force: bool = False,
        priority: bool = False,
    ) -> None:
        self._tile_requests.request_detail(
            coords,
            tile_size=tile_size,
            force=force,
            priority=priority,
        )

    def _apply_shapes(self, shapes: List[cv.Shape]) -> None:
        if not self._mounted or self.page is None:
            return
        # Assign a fresh list so Flutter never iterates a list mid-mutation.
        self._canvas.shapes = list(shapes)
        safe_update(self._canvas)

    def _build_region_cell(
        self,
        x: float,
        y: float,
        size: float,
        color: str,
        coord: Tuple[int, int],
        file_size: int,
    ) -> List[cv.Shape]:
        del file_size
        meta = self._service.get_region_meta(coord)
        value_label = None
        if self._display_mode in {"biome", "structure"}:
            value_label = get_region_value_label(
                self._display_mode,
                coord,
                self._current_data.get(coord, 0),
                meta,
                self._cached_stats or {},
            )
        return map_shapes.region_cell(
            x,
            y,
            size,
            color,
            coord,
            selected=coord == self._selected_cell,
            view_level=self._view_level,
            show_coordinates=self._show_coordinates,
            tile_src=self._tile_src(coord) if self._use_topview else None,
            coord_label=self._coord_label_for_region,
            value_label=value_label,
        )

    def _build_chunk_grid(
        self,
        x: float,
        y: float,
        size: float,
        region_coord: Tuple[int, int],
        *,
        show_block_grid: bool = False,
    ) -> List[cv.Shape]:
        shapes, chunk_bounds, block_bounds = map_shapes.chunk_grid(
            x,
            y,
            size,
            region_coord,
            show_block_grid=show_block_grid,
            show_coordinates=self._show_coordinates,
            selected_chunk=self._selected_chunk,
        )
        self._chunk_bounds.update(chunk_bounds)
        self._block_bounds.update(block_bounds)
        return shapes

    def _build_info_overlay(self) -> List[cv.Shape]:
        return map_shapes.info_overlay(
            width=self.width or 800,
            height=self.height or 600,
            display_mode=self._display_mode,
            view_level=self._view_level,
            scale=self._scale,
            is_scanning=self._service.is_scanning,
            scan_progress=self._service.scan_progress,
            selected_region=self._selected_cell,
            selected_chunk=self._selected_chunk,
            show_coordinates=self._show_coordinates,
        )

    def _build_marker_overlay(self) -> List[cv.Shape]:
        return self._marker_layer.draw(
            self._viewport,
            width=float(self.width or 800),
            height=float(self.height or 600),
        )

    # ------------------------------------------------------------------ lifecycle / scan
    async def _update_loop(self) -> None:
        while self._service.is_scanning:
            count = self._service.progress_info.scanned_files
            if count != self._last_drawn_count:
                self._last_drawn_count = count
                self._request_rebuild()
            await asyncio.sleep(0.2)
        self._last_drawn_count = -1
        self._request_rebuild()
        if self._on_selection_changed:
            # Selection callback also mutates UI controls — hop to page loop.
            page = self.page
            if page is not None:
                run_on_ui(
                    cast(ft.Page, page),
                    self._on_selection_changed,
                    None,
                    None,
                    None,
                )
            else:
                try:
                    self._on_selection_changed(None, None, None)
                except Exception:
                    # UI best-effort: control may already be unmounted.
                    pass

    def did_mount(self) -> None:
        """控件挂到页面后启用瓦片回调与扫描进度循环。"""
        if self._disposed:
            return
        super().did_mount()
        self._mounted = True
        self._service.set_tile_ready_callback(self._tile_ready_callback)
        if self._needs_initial_draw:
            self._request_rebuild()
        if self._service.is_scanning:
            self._start_update_loop()

    def will_unmount(self) -> None:
        """卸载时取消动画/循环，并摘掉可能指向本视图的服务回调。"""
        self._mounted = False
        self._needs_initial_draw = True
        self._camera.cancel()
        self._metadata_pending.clear()
        self._rebuild_scheduler.cancel()
        self._stop_update_loop()
        self._surface_layer.suspend()
        self._release_tile_ready_callback()
        super().will_unmount()

    def dispose(self) -> None:
        """释放视图拥有的调度器与 Base64 瓦片缓存；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._mounted = False
        self._camera.cancel()
        self._metadata_pending.clear()
        self._rebuild_scheduler.cancel()
        self._stop_update_loop()
        self._tile_requests.reset()
        self._surface_layer.close()
        self._release_tile_ready_callback()
        self._tile_sources.close()

    def _release_tile_ready_callback(self) -> None:
        """仅摘除当前视图仍拥有的服务回调。"""
        try:
            if (
                getattr(self._service, "_tile_ready_callback", None)
                is self._tile_ready_callback
            ):
                self._service.set_tile_ready_callback(None)
        except Exception:
            # UI teardown is best-effort; service may already be closed.
            pass

    def _schedule_task(
        self,
        coro: Coroutine[Any, Any, Any],
    ) -> Optional[ScheduledTask]:
        """Schedule a coroutine on the UI event loop when possible."""
        try:
            page = cast(Optional[ft.Page], self.page)
        except RuntimeError:
            page = None
        return schedule_coroutine(coro, page=page)

    def _start_update_loop(self) -> None:
        if self._update_task is None or self._update_task.done():
            self._update_task = self._schedule_task(self._update_loop())

    def _stop_update_loop(self) -> None:
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
        self._update_task = None

    # ------------------------------------------------------------------ public API (region_tab)
    def start_scan(self, region_dir: str) -> None:
        """异步启动静默区域扫描，并打开进度刷新循环。

        Args:
            region_dir: 含 ``r.x.z.mca`` 的区域目录路径。
        """
        self._schedule_task(self._service.start_silent_scan(region_dir))
        self._start_update_loop()

    def refresh(self) -> None:
        """重置相机到世界级默认视口并重绘（保留选择状态）。"""
        self._viewport.reset()
        self._view_level = "world"
        self._request_rebuild()

    def reset_view(self) -> None:
        """重置相机、清空区域/区块选择并回到 world 层级。"""
        self._viewport.reset()
        self._selected_cell = None
        self._selected_chunk = None
        self._view_level = "world"
        self._request_rebuild()

    def fit_to_view(self, padding: float = 0.86) -> None:
        """Recompute scale/offset so all known regions are centered in the viewport.

        Used when entering app-wide fullscreen so the map doesn't keep the
        previous (smaller) viewport camera.
        """
        data = self._service.get_all_data()
        view_w = float(self.width or 800)
        view_h = float(self.height or 600)
        if not data or view_w <= 1 or view_h <= 1:
            self._viewport.reset()
            self._view_level = "world"
            self._request_rebuild()
            return

        target = self._viewport.fit(
            data.keys(),
            view_w,
            view_h,
            padding=padding,
            min_fit_scale=self.MIN_SCALE,
            max_fit_scale=8.0,
        )
        self._viewport.apply(target)
        self._view_level = view_level_from_scale(self._scale)
        self._request_rebuild()

    def resize_map(self, width: int, height: int, *, refit: bool = False) -> None:
        """调整画布尺寸；默认保留相机，``refit`` 时重新 fit 全图。

        Args:
            width: 新宽度（会钳制到合理下限）。
            height: 新高度。
            refit: 为 True 时调用 :meth:`fit_to_view` 重算相机。
        """
        width = max(120, int(width))
        height = max(100, int(height))
        if self.width == width and self.height == height and not refit:
            return
        self.width = width
        self.height = height
        if refit:
            self.fit_to_view()
        else:
            # Keep camera when adapting to layout; only re-center on explicit reset/refit.
            self._request_rebuild()

    def _on_canvas_resize(self, e: Any) -> None:
        """Adapt to parent layout size (border-aware fill)."""
        try:
            w = int(getattr(e, "width", 0) or 0)
            h = int(getattr(e, "height", 0) or 0)
        except (TypeError, ValueError, AttributeError):
            return
        if w < 80 or h < 80:
            return
        self.resize_map(w, h)

    def toggle_coordinates(self) -> bool:
        """切换区域坐标标签显示。

        Returns:
            切换后是否显示坐标。
        """
        self._show_coordinates = not self._show_coordinates
        self._request_rebuild()
        return self._show_coordinates

    def toggle_empty_regions(self) -> bool:
        """切换是否绘制无数据的空区域占位格。

        Returns:
            切换后是否显示空区域。
        """
        self._show_empty_regions = not self._show_empty_regions
        self._request_rebuild()
        return self._show_empty_regions

    def toggle_grid(self) -> bool:
        """Toggle the optional selected-region grid without touching tiles."""
        self._show_grid = not self._show_grid
        self._request_rebuild()
        return self._show_grid

    def toggle_markers(self) -> bool:
        """Toggle the dynamic waypoint overlay."""
        visible = self._marker_layer.toggle()
        self._request_rebuild()
        return visible

    def apply_layer_state(
        self,
        layers: MapLayerState | MapLayerStateSnapshot,
    ) -> None:
        """Apply persisted layer switches when a dimension is restored."""
        self._show_coordinates = bool(layers.show_coordinates)
        self._show_grid = bool(layers.show_grid)
        self._show_empty_regions = bool(layers.show_empty_regions)
        self._marker_layer.set_visible(bool(layers.show_markers))
        self._request_rebuild()

    def set_markers(self, markers: List[MapMarker]) -> None:
        """Replace the marker snapshot without sharing mutable metadata."""
        self._marker_layer.set_markers(markers)
        self._request_rebuild()

    def get_markers(self) -> list[MapMarker]:
        """返回当前标记快照（副本，避免外部共享可变元数据）。"""
        return self._marker_layer.snapshot()

    def select_marker(self, marker_id: Optional[str]) -> None:
        """Highlight a marker selected outside the canvas hit-test layer."""
        self._marker_layer.select(marker_id)
        self._request_rebuild()

    def focus_block(
        self,
        block_x: int,
        block_z: int,
        *,
        animate: bool = True,
        target_scale: Optional[float] = None,
    ) -> None:
        """Center the camera on a Minecraft block coordinate."""
        view_w = float(self.width or 800)
        view_h = float(self.height or 600)
        scale = (
            max(self._scale, self.SCALE_REGION)
            if target_scale is None
            else float(target_scale)
        )
        world_x, world_z = self._viewport.block_to_world(block_x, block_z)
        target = ViewportTarget(
            scale,
            view_w / 2.0 - world_x * scale,
            view_h / 2.0 - world_z * scale,
        )
        self._apply_camera_target(
            target,
            animate=animate,
            sync_view_level=True,
        )

    def block_at_screen(self, x: float, y: float) -> Optional[Tuple[int, int]]:
        """将屏幕像素映射为方块坐标；落在 cell gap 时返回 None。

        Args:
            x: 相对画布的 X 像素。
            y: 相对画布的 Y 像素。

        Returns:
            ``(block_x, block_z)``，或无法映射时为 None。
        """
        return self._viewport.screen_to_block(x, y)

    def get_center_block(self) -> Tuple[int, int]:
        """Return a stable block anchor for dimension-specific camera state."""
        center_x = float(self.width or 800) / 2.0
        center_y = float(self.height or 600) / 2.0
        block = self._viewport.screen_to_block(center_x, center_y)
        if block is not None:
            return block
        return self._viewport.nearest_block_at_screen(center_x, center_y)

    def get_camera_scale(self) -> float:
        """当前相机缩放（世界单位到像素）。"""
        return float(self._scale)

    def get_selected_chunk(self) -> Optional[Tuple[int, int]]:
        """当前选中的世界区块坐标，未选中则为 None。"""
        return self._selected_chunk

    def set_display_mode(self, mode: str) -> None:
        """切换热力图/俯视/生物群系/结构等显示模式。

        Args:
            mode: ``activity`` / ``topview`` / ``biome`` / ``structure``；
                非法值静默忽略。
        """
        if mode not in {"activity", "topview", "biome", "structure"}:
            return
        self._display_mode = mode
        self._use_topview = mode in {"activity", "topview"}
        self._surface_layer.mark_dirty()
        self._request_rebuild()

    def get_display_mode(self) -> str:
        """当前显示模式字符串（activity/topview/biome/structure）。"""
        return self._display_mode

    def set_detail_level(self, level: str) -> None:
        """手动固定语义层级，或 ``auto`` 跟随当前缩放。

        Args:
            level: ``auto`` / ``world`` / ``region`` / ``chunk`` / ``block``；
                非法值忽略。固定到 world 会清空区块选择并 fit 全图。
        """
        if level not in {"auto", "region", "chunk", "world", "block"}:
            return
        if level == "auto":
            self._view_level = view_level_from_scale(self._scale)
            self._request_rebuild()
            return
        self._detail_level = level
        self._view_level = cast(MapViewLevel, level)
        if self._view_level == "world":
            self._selected_chunk = None
            self.fit_to_view()
        elif self._view_level == "region" and self._selected_cell is not None:
            self._selected_chunk = None
            self._focus_region(self._selected_cell, animate=True, target_fill=0.72)
        elif self._view_level == "chunk" and self._selected_cell is not None:
            self._focus_region(self._selected_cell, animate=True, target_fill=0.92)
        elif self._view_level == "block" and self._selected_chunk is not None:
            self._focus_chunk(self._selected_chunk, animate=True, target_fill=0.85)
        elif self._view_level == "block" and self._selected_cell is not None:
            self._focus_region(self._selected_cell, animate=True, target_fill=0.98)
            self._view_level = "block"
        else:
            self._request_rebuild()

    def get_detail_level(self) -> str:
        """当前语义视口层级（可能与手动 detail 设定因缩放而不同）。"""
        return self._view_level

    def zoom_in(self) -> None:
        """以视口中心为支点放大一级。"""
        self._zoom_about_center(1.22)

    def zoom_out(self) -> None:
        """以视口中心为支点缩小一级。"""
        self._zoom_about_center(0.82)

    def _zoom_about_center(self, factor: float) -> None:
        cx = (self.width or 800) / 2
        cy = (self.height or 600) / 2
        self._zoom_pivot_x = cx
        self._zoom_pivot_y = cy
        self._camera.animate_zoom_about(factor, cx, cy)

    def _on_camera_frame(self) -> None:
        try:
            self._sync_view_level_from_scale(notify=False)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        self._rebuild_scheduler.schedule()

    def _on_camera_complete(self) -> None:
        try:
            self._sync_view_level_from_scale(notify=True)
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        self._request_rebuild()

    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        """当前选中的区域坐标 ``(region_x, region_z)``，未选中为 None。"""
        return self._selected_cell
