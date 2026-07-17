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
import time
from concurrent.futures import Future as ConcurrentFuture
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast

import flet as ft

try:
    import flet.canvas as cv
except ImportError as exc:  # pragma: no cover
    raise ImportError("flet.canvas is not available in this Flet version") from exc

from app.ui.utils import run_on_ui
from app.ui.views.explorer.map.color_schemes import (
    BACKGROUND_COLOR,
    EMPTY_REGION_COLOR,
    ORIGIN_COLOR,
    SELECTED_BORDER_COLOR,
    get_mode_title,
    get_region_color,
)
from core.mca.topview_renderer import (
    DEFAULT_TILE_SIZE,
    DETAIL_TILE_SIZE,
)
from core.mca.map_coordinates import (
    format_chunk_block_range,
    format_region_block_range,
    format_region_coordinate_label,
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
    from app.services.region_map_service import RegionMapService


MapSelectionCallback = Callable[
    [Optional[Tuple[int, int]], Optional[int], Optional[Dict[str, Any]]], None
]
ScheduledTask = asyncio.Future[Any] | ConcurrentFuture[Any]


class McaMapView(ft.Container):
    """Minimal MCA region map (presence grid, not size heatmap)."""

    BACKGROUND_COLOR = BACKGROUND_COLOR
    EMPTY_REGION_COLOR = EMPTY_REGION_COLOR
    ORIGIN_COLOR = ORIGIN_COLOR
    CELL_SIZE = 32
    CELL_GAP = 2

    MIN_SCALE = MIN_SCALE
    MAX_SCALE = MAX_SCALE
    SCALE_REGION = SCALE_REGION
    SCALE_CHUNK = SCALE_CHUNK
    SCALE_BLOCK = SCALE_BLOCK

    def __init__(
        self,
        map_service: RegionMapService,
        on_selection_changed: Optional[MapSelectionCallback] = None,
        width: int = 700,
        height: int = 450,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._service = map_service
        self._on_selection_changed = on_selection_changed

        self._viewport = McaViewport(
            cell_size=float(self.CELL_SIZE),
            cell_gap=float(self.CELL_GAP),
            min_scale=self.MIN_SCALE,
            max_scale=self.MAX_SCALE,
        )
        self._show_coordinates = True
        self._show_empty_regions = False
        self._display_mode = "topview"
        self._detail_level = "region"
        self._use_topview = True

        self._selection = McaMapSelection()
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._chunk_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._block_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._cached_stats: Optional[Dict[str, Any]] = None
        # base64 cache for canvas Image.src (derived from service PNG bytes)
        self._tile_src_cache: Dict[Tuple[int, int], str] = {}
        self._tile_src_generation = -1

        self._last_x = 0.0
        self._last_y = 0.0
        self._needs_initial_draw = True
        self._update_task: Optional[ScheduledTask] = None
        self._last_drawn_count = -1
        self._mounted = False

        self._rebuild_pending = False
        self._rebuild_timer: Optional[threading.Timer] = None
        self._last_rebuild_ts = 0.0
        self._min_rebuild_interval = 1.0 / 60.0
        # Smooth zoom animation state (world-space pivot + ease-out)
        self._zoom_anim_timer: Optional[threading.Timer] = None
        self._zoom_anim_active = False
        self._zoom_anim_start = self._viewport.current_target
        self._zoom_anim_target = self._viewport.current_target
        self._zoom_anim_t0 = 0.0
        self._zoom_anim_duration = 0.16
        # Pointer used for level auto-switch while zooming.
        self._zoom_pivot_x = 0.0
        self._zoom_pivot_y = 0.0
        self._last_notified_level: Optional[str] = None

        self.width = width
        self.height = height
        self.bgcolor = self.BACKGROUND_COLOR
        self.border_radius = 0
        self.expand = True

        self._canvas = cv.Canvas(
            width=width,
            height=height,
            expand=True,
            shapes=self._empty_shapes(),
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
            width=width,
            height=height,
            expand=True,
        )
        self.content = ft.Stack(
            [self._canvas, self._gesture],
            expand=True,
        )

        # Progressive topview: service notifies when a tile finishes rendering.
        self._service.set_tile_ready_callback(self._on_tile_ready)

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
            # Only rebuild if the cell is currently relevant.
            if coord in self._current_data or not self._current_data:
                self._schedule_rebuild()
        except Exception:
            pass

    def _tile_src(self, coord: Tuple[int, int]) -> Optional[str]:
        """Return base64 PNG for coord, caching decoded form for canvas."""
        import base64

        generation = self._service.get_topview_generation()
        if generation != self._tile_src_generation:
            self._tile_src_cache.clear()
            self._tile_src_generation = generation
        cached = self._tile_src_cache.get(coord)
        if cached is not None:
            return cached
        raw = self._service.get_topview_tile(coord)
        if not raw:
            return None
        src = base64.b64encode(raw).decode("ascii")
        self._tile_src_cache[coord] = src
        return src

    # ------------------------------------------------------------------ UI helpers
    def _empty_shapes(self) -> List[cv.Shape]:
        return [
            cv.Rect(
                0,
                0,
                self.width or 800,
                self.height or 600,
                paint=ft.Paint(color=self.BACKGROUND_COLOR),
            )
        ]

    def _request_rebuild(self) -> None:
        """Marshal canvas rebuild onto the Flet UI thread.

        Canvas.shapes must only be mutated on the UI thread. Background timers,
        topview workers, and off-loop scan tasks all funnel through here.
        """
        if not self._mounted:
            return
        try:
            page = self.page
        except RuntimeError:
            return
        if page is None:
            return
        run_on_ui(cast(ft.Page, page), self._rebuild_canvas_safe)

    def _rebuild_canvas_safe(self) -> None:
        if not self._mounted or self.page is None:
            return
        try:
            self._rebuild_canvas()
        except Exception:
            pass

    def _schedule_rebuild(self) -> None:
        """Rate-limit rebuild requests, then hop to the UI thread."""
        now = time.monotonic()
        elapsed = now - self._last_rebuild_ts
        if elapsed >= self._min_rebuild_interval and not self._rebuild_pending:
            self._last_rebuild_ts = now
            self._request_rebuild()
            return
        if self._rebuild_pending:
            return
        self._rebuild_pending = True
        delay = max(0.0, self._min_rebuild_interval - elapsed)

        def _fire() -> None:
            self._rebuild_pending = False
            self._last_rebuild_ts = time.monotonic()
            try:
                self._request_rebuild()
            except Exception:
                pass

        try:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()
        except Exception:
            pass
        self._rebuild_timer = threading.Timer(delay, _fire)
        self._rebuild_timer.daemon = True
        self._rebuild_timer.start()

    def _cancel_rebuild_timer(self) -> None:
        try:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()
        except Exception:
            pass
        self._rebuild_timer = None
        self._rebuild_pending = False

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
        self._schedule_rebuild()

    def _on_tap(self, e: ft.TapEvent) -> None:
        local_position = e.local_position
        if local_position is None:
            return
        tap_x = local_position.x
        tap_y = local_position.y

        # Chunk/block-level selection when deeply zoomed into a region.
        if self._view_level in {"chunk", "block"} and self._chunk_bounds:
            for chunk_coord, bounds in self._chunk_bounds.items():
                bx, by, bw, bh = bounds
                if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                    self._selected_chunk = chunk_coord
                    region = (chunk_coord[0] // 32, chunk_coord[1] // 32)
                    self._selected_cell = region
                    size = self._current_data.get(region, 0)
                    level = "block" if self._view_level == "block" else "chunk"
                    if self._on_selection_changed:
                        self._on_selection_changed(
                            region,
                            size,
                            {
                                "level": level,
                                "chunk_coord": chunk_coord,
                                "block_range": format_chunk_block_range(chunk_coord),
                            },
                        )
                    if (
                        self._view_level == "block"
                        or self._scale >= self.SCALE_BLOCK * 0.85
                    ):
                        self._focus_chunk(chunk_coord, animate=True, target_fill=0.78)
                        self._view_level = "block"
                    self._request_rebuild()
                    return

        for coord, bounds in self._cell_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                if coord not in self._current_data:
                    break
                self._selected_cell = coord
                self._selected_chunk = None
                size = self._current_data[coord]
                if self._on_selection_changed:
                    self._on_selection_changed(
                        coord,
                        size,
                        {
                            "level": "region",
                            "block_range": format_region_block_range(coord),
                        },
                    )
                # Single click: local zoom into the region (not full chunk level).
                self._focus_region(coord, animate=True, target_fill=0.72)
                self._view_level = "region"
                break

    def _on_double_tap(self, e: Any) -> None:
        """Double-click: zoom to chunk level, or deeper into a single chunk."""
        tap_x = getattr(getattr(e, "local_position", None), "x", None)
        tap_y = getattr(getattr(e, "local_position", None), "y", None)
        if tap_x is None or tap_y is None:
            # Some Flet versions only provide local_x/local_y on double tap.
            tap_x = getattr(e, "local_x", (self.width or 800) / 2)
            tap_y = getattr(e, "local_y", (self.height or 600) / 2)

        # If already at chunk/block and a chunk is under the pointer, dive in.
        hit_chunk = self._hit_chunk(float(tap_x), float(tap_y))
        if hit_chunk is not None and self._view_level in {"chunk", "block"}:
            region = (hit_chunk[0] // 32, hit_chunk[1] // 32)
            self._selected_cell = region
            self._selected_chunk = hit_chunk
            size = self._current_data.get(region, 0)
            if self._on_selection_changed:
                self._on_selection_changed(
                    region,
                    size,
                    {
                        "level": "block",
                        "chunk_coord": hit_chunk,
                        "block_range": format_chunk_block_range(hit_chunk),
                    },
                )
            self._focus_chunk(hit_chunk, animate=True, target_fill=0.85)
            self._view_level = "block"
            return

        hit = self._hit_region(float(tap_x), float(tap_y))
        if hit is None:
            # If already focused on a region, deepen into chunk level there.
            if self._selected_cell is not None:
                hit = self._selected_cell
            else:
                return

        self._selected_cell = hit
        self._selected_chunk = None
        size = self._current_data.get(hit, 0)
        if self._on_selection_changed:
            self._on_selection_changed(
                hit,
                size,
                {
                    "level": "chunk",
                    "block_range": format_region_block_range(hit),
                },
            )
        # Stronger zoom so one region fills almost the whole view → chunk grid readable.
        self._focus_region(hit, animate=True, target_fill=0.92)
        self._view_level = "chunk"
        # Ensure hi-res tile for chunk inspection.
        if self._use_topview:
            try:
                self._service.request_topview_tiles(
                    [hit],
                    tile_size=DETAIL_TILE_SIZE,
                    force=True,
                    priority=True,
                )
            except TypeError:
                self._service.request_topview_tiles([hit], tile_size=DETAIL_TILE_SIZE)

    def _on_secondary_tap(self, e: Any) -> None:
        """Right-click: step back overview (block→chunk→region→world)."""
        if self._view_level == "block":
            self._view_level = "chunk"
            if self._selected_cell is not None:
                self._focus_region(self._selected_cell, animate=True, target_fill=0.88)
            if self._on_selection_changed and self._selected_cell is not None:
                size = self._current_data.get(self._selected_cell, 0)
                detail: Dict[str, Any] = {
                    "level": "chunk",
                    "block_range": format_region_block_range(self._selected_cell),
                }
                if self._selected_chunk is not None:
                    detail["chunk_coord"] = self._selected_chunk
                    detail["block_range"] = format_chunk_block_range(
                        self._selected_chunk
                    )
                self._on_selection_changed(self._selected_cell, size, detail)
            return

        if self._view_level == "chunk":
            self._view_level = "region"
            self._selected_chunk = None
            if self._selected_cell is not None:
                self._focus_region(self._selected_cell, animate=True, target_fill=0.55)
            else:
                self.fit_to_view(padding=0.82)
            if self._on_selection_changed and self._selected_cell is not None:
                size = self._current_data.get(self._selected_cell, 0)
                self._on_selection_changed(
                    self._selected_cell,
                    size,
                    {
                        "level": "region",
                        "block_range": format_region_block_range(
                            self._selected_cell
                        ),
                    },
                )
            return

        # region / world → full overview
        self._view_level = "world"
        self._selected_chunk = None
        # Keep selected region highlight, but zoom out to whole map.
        self.fit_to_view(padding=0.82)
        if self._on_selection_changed:
            # Clear side-panel detail to overview status.
            self._on_selection_changed(None, None, {"level": "world"})

    def _hit_region(self, tap_x: float, tap_y: float) -> Optional[Tuple[int, int]]:
        for coord, bounds in self._cell_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                if coord in self._current_data:
                    return coord
        return None

    def _hit_chunk(self, tap_x: float, tap_y: float) -> Optional[Tuple[int, int]]:
        for chunk_coord, bounds in self._chunk_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                return chunk_coord
        return None

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
            neighbors = [
                (coord[0] + dx, coord[1] + dz)
                for dz in (-1, 0, 1)
                for dx in (-1, 0, 1)
                if (coord[0] + dx, coord[1] + dz) in self._current_data
                or (dx, dz) == (0, 0)
            ]
            try:
                self._service.request_topview_tiles(
                    neighbors,
                    tile_size=DETAIL_TILE_SIZE,
                    force=True,
                    priority=True,
                )
            except TypeError:
                # Older service signature fallback
                self._service.request_topview_tiles(
                    neighbors, tile_size=DETAIL_TILE_SIZE
                )

        if animate:
            self._animate_camera_to(
                target.scale,
                target.offset_x,
                target.offset_y,
                duration=0.28,
            )
        else:
            self._viewport.apply(target)
            self._request_rebuild()

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
            try:
                self._service.request_topview_tiles(
                    [(rx, rz)],
                    tile_size=DETAIL_TILE_SIZE,
                    force=True,
                    priority=True,
                )
            except TypeError:
                self._service.request_topview_tiles(
                    [(rx, rz)], tile_size=DETAIL_TILE_SIZE
                )

        if animate:
            self._animate_camera_to(
                target.scale,
                target.offset_x,
                target.offset_y,
                duration=0.28,
            )
        else:
            self._viewport.apply(target)
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
        self._animate_zoom_toward(zoom_factor, float(pointer_x), float(pointer_y))

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

        prev = self._view_level
        new_level = view_level_from_scale(self._scale)
        level_order = {"world": 0, "region": 1, "chunk": 2, "block": 3}
        going_deeper = level_order.get(new_level, 0) > level_order.get(prev, 0)
        going_out = level_order.get(new_level, 0) < level_order.get(prev, 0)

        if new_level == prev:
            if new_level in {"chunk", "block"}:
                self._auto_select_under_pointer(px, py, new_level, notify=False)
            return False

        self._view_level = new_level

        if going_out and new_level in {"world", "region"}:
            self._selected_chunk = None

        if going_deeper or new_level in {"chunk", "block"}:
            self._auto_select_under_pointer(px, py, new_level, notify=False)
            if self._use_topview and self._selected_cell is not None:
                try:
                    self._service.request_topview_tiles(
                        [self._selected_cell],
                        tile_size=DETAIL_TILE_SIZE,
                        force=True,
                        priority=True,
                    )
                except TypeError:
                    self._service.request_topview_tiles(
                        [self._selected_cell], tile_size=DETAIL_TILE_SIZE
                    )

        if notify and (new_level != prev or new_level != self._last_notified_level):
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
        if not self._on_selection_changed:
            return
        self._last_notified_level = level
        if level == "world" or self._selected_cell is None:
            self._on_selection_changed(None, None, {"level": "world"})
            return
        region = self._selected_cell
        size = self._current_data.get(region, 0)
        detail: Dict[str, Any] = {"level": level}
        if self._selected_chunk is not None and level in {"chunk", "block"}:
            detail["chunk_coord"] = self._selected_chunk
            detail["block_range"] = format_chunk_block_range(
                self._selected_chunk
            )
        else:
            detail["block_range"] = format_region_block_range(region)
        self._on_selection_changed(region, size, detail)

    # ------------------------------------------------------------------ draw
    def _rebuild_canvas(self) -> None:
        self._current_data = self._service.get_all_data()
        self._cached_stats = self._service.get_statistics()
        shapes: List[cv.Shape] = list(self._empty_shapes())
        view_w = self.width or 800
        view_h = self.height or 600

        if not self._current_data:
            shapes.extend(self._build_empty_state(view_w, view_h))
            shapes.extend(self._build_info_overlay())
            self._apply_shapes(shapes)
            return

        coords = list(self._current_data.keys())
        self._cell_bounds.clear()
        self._chunk_bounds.clear()
        self._block_bounds.clear()
        shapes.extend(self._build_origin_marker(self._offset_x, self._offset_y))

        draw_bounds = self._prepare_visible_bounds(coords, view_w, view_h)
        if draw_bounds is None:
            self._apply_shapes(shapes)
            return
        region_shapes, missing = self._build_visible_regions(
            draw_bounds,
            view_w,
            view_h,
        )
        shapes.extend(region_shapes)
        self._request_visible_tiles(missing)
        self._request_selected_detail_tiles()

        shapes.extend(self._build_info_overlay())
        self._apply_shapes(shapes)
        self._needs_initial_draw = False

    def _build_empty_state(self, view_w: float, view_h: float) -> List[cv.Shape]:
        return [
            cv.Text(
                x=view_w / 2 - 90,
                y=view_h / 2 - 30,
                value="🗺️",
                style=ft.TextStyle(size=48, color="#888888"),
            ),
            cv.Text(
                x=view_w / 2 - 95,
                y=view_h / 2 + 30,
                value="设置当前存档后显示区域地图",
                style=ft.TextStyle(size=16, color="#CCCCCC"),
            ),
        ]

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
                min_fit_scale=0.35,
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
        show_chunk_grid = (
            self._view_level in {"chunk", "block"}
            or self._scale >= self.SCALE_CHUNK
        )
        show_block_grid = (
            self._view_level == "block" or self._scale >= self.SCALE_BLOCK
        )
        min_x, max_x, min_z, max_z = bounds
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                coord = (x, z)
                rect = self._viewport.region_rect(coord)
                if self._rect_outside_view(rect, view_w, view_h):
                    continue
                self._cell_bounds[coord] = rect
                if coord in self._current_data:
                    shapes.extend(self._build_present_region(
                        coord,
                        rect,
                        show_chunk_grid,
                        show_block_grid,
                    ))
                    if self._use_topview and not self._service.has_topview_tile(coord):
                        missing.append(coord)
                elif self._show_empty_regions:
                    shapes.append(self._build_empty_region(rect))
        return shapes, missing

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
        color = get_region_color(file_size, self._cached_stats or {})
        shapes = self._build_region_cell(x, y, size, color, coord, file_size)
        if show_chunk_grid or size >= 160:
            shapes.extend(self._build_chunk_grid(
                x,
                y,
                size,
                coord,
                show_block_grid=show_block_grid,
            ))
        return shapes

    def _build_empty_region(
        self,
        rect: Tuple[float, float, float, float],
    ) -> cv.Rect:
        x, y, width, height = rect
        return cv.Rect(
            x,
            y,
            width,
            height,
            paint=ft.Paint(
                color=self.EMPTY_REGION_COLOR,
                style=ft.PaintingStyle.STROKE,
                stroke_width=0.5,
            ),
        )

    def _request_visible_tiles(self, missing: List[Tuple[int, int]]) -> None:
        if missing:
            self._service.request_topview_tiles(
                missing,
                tile_size=DEFAULT_TILE_SIZE,
            )

    def _request_selected_detail_tiles(self) -> None:
        if (
            not self._use_topview
            or self._selected_cell is None
            or self._scale < 2.2
        ):
            return
        selected = self._selected_cell
        nearby = [
            (selected[0] + dx, selected[1] + dz)
            for dz in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (selected[0] + dx, selected[1] + dz) in self._current_data
        ]
        missing = [
            coord
            for coord in nearby
            if not self._service.has_topview_tile(
                coord,
                min_size=DETAIL_TILE_SIZE,
            )
        ]
        if not missing:
            return
        try:
            self._service.request_topview_tiles(
                missing,
                tile_size=DETAIL_TILE_SIZE,
                force=True,
                priority=True,
            )
        except TypeError:
            self._service.request_topview_tiles(
                missing,
                tile_size=DETAIL_TILE_SIZE,
            )

    def _apply_shapes(self, shapes: List[cv.Shape]) -> None:
        if not self._mounted or self.page is None:
            return
        # Assign a fresh list so Flutter never iterates a list mid-mutation.
        self._canvas.shapes = list(shapes)
        try:
            self._canvas.update()
        except RuntimeError:
            pass

    def _build_region_cell(
        self,
        x: float,
        y: float,
        size: float,
        color: str,
        coord: Tuple[int, int],
        file_size: int,
    ) -> List[cv.Shape]:
        shapes: List[cv.Shape] = []
        tile_src = self._tile_src(coord) if self._use_topview else None
        if tile_src:
            shapes.append(
                cv.Image(
                    src=tile_src,
                    x=x,
                    y=y,
                    width=size,
                    height=size,
                )
            )
        else:
            # Placeholder until topview tile is ready
            shapes.append(cv.Rect(x, y, size, size, paint=ft.Paint(color=color)))
        selected = coord == self._selected_cell
        shapes.append(
            cv.Rect(
                x,
                y,
                size,
                size,
                paint=ft.Paint(
                    color=SELECTED_BORDER_COLOR if selected else "#00000055",
                    style=ft.PaintingStyle.STROKE,
                    stroke_width=3 if selected else 1,
                ),
            )
        )
        # Hide region labels once inside a single chunk — they clutter the mesh.
        if self._show_coordinates and size >= 22 and self._view_level != "block":
            label = self._coord_label_for_region(coord, size)
            # Multi-line for mid/near ranges when space allows.
            if "\n" in label:
                for i, line in enumerate(label.split("\n")[:2]):
                    shapes.append(
                        cv.Text(
                            x=x + 4,
                            y=y + 4 + i * 12,
                            value=line,
                            style=ft.TextStyle(
                                size=9 if size < 70 else 10,
                                color="#FFFFFF" if tile_src else "#F5F5DC",
                            ),
                        )
                    )
            else:
                shapes.append(
                    cv.Text(
                        x=x + 4,
                        y=y + 5,
                        value=label,
                        style=ft.TextStyle(
                            size=9 if size < 70 else 11,
                            color="#FFFFFF" if tile_src else "#F5F5DC",
                        ),
                    )
                )
        return shapes

    def _build_chunk_grid(
        self,
        x: float,
        y: float,
        size: float,
        region_coord: Tuple[int, int],
        *,
        show_block_grid: bool = False,
    ) -> List[cv.Shape]:
        """Draw 32×32 chunk mesh inside a region; optionally 16×16 block mesh."""
        shapes: List[cv.Shape] = []
        chunk_size = size / 32.0
        if chunk_size < 2.5:
            return shapes
        rx, rz = region_coord
        line_color = "#00000066" if chunk_size >= 4 else "#00000040"
        # Grid lines (skip outer edge; region border already drawn).
        for i in range(1, 32):
            pos = i * chunk_size
            shapes.append(
                cv.Line(
                    x + pos,
                    y,
                    x + pos,
                    y + size,
                    paint=ft.Paint(color=line_color, stroke_width=0.6),
                )
            )
            shapes.append(
                cv.Line(
                    x,
                    y + pos,
                    x + size,
                    y + pos,
                    paint=ft.Paint(color=line_color, stroke_width=0.6),
                )
            )
        # Hit bounds for every chunk; labels only when large enough.
        for local_z in range(32):
            for local_x in range(32):
                cx = rx * 32 + local_x
                cz = rz * 32 + local_z
                bx = x + local_x * chunk_size
                by = y + local_z * chunk_size
                self._chunk_bounds[(cx, cz)] = (bx, by, chunk_size, chunk_size)
                if self._show_coordinates and chunk_size >= 14 and not show_block_grid:
                    # Game block coords of chunk origin.
                    shapes.append(
                        cv.Text(
                            x=bx + 1,
                            y=by + 1,
                            value=f"{cx * 16},{cz * 16}",
                            style=ft.TextStyle(size=8, color="#FFECB3"),
                        )
                    )

        if show_block_grid and chunk_size >= 24:
            shapes.extend(
                self._build_block_grid_for_region(x, y, chunk_size, region_coord)
            )

        # Highlight selected chunk.
        if self._selected_chunk is not None:
            scx, scz = self._selected_chunk
            if scx // 32 == rx and scz // 32 == rz:
                lx = scx - rx * 32
                lz = scz - rz * 32
                shapes.append(
                    cv.Rect(
                        x + lx * chunk_size,
                        y + lz * chunk_size,
                        chunk_size,
                        chunk_size,
                        paint=ft.Paint(
                            color="#FFD54F",
                            style=ft.PaintingStyle.STROKE,
                            stroke_width=max(1.5, min(3.0, chunk_size / 3)),
                        ),
                    )
                )
        return shapes

    def _build_block_grid_for_region(
        self,
        region_x: float,
        region_y: float,
        chunk_size: float,
        region_coord: Tuple[int, int],
    ) -> List[cv.Shape]:
        """Draw 16×16 block mesh for the selected (or center) chunk."""
        shapes: List[cv.Shape] = []
        block_px = chunk_size / 16.0
        if block_px < 2.0:
            return shapes

        rx, rz = region_coord
        targets: List[Tuple[int, int]] = []
        if self._selected_chunk is not None:
            scx, scz = self._selected_chunk
            if scx // 32 == rx and scz // 32 == rz:
                targets.append((scx - rx * 32, scz - rz * 32))
        if not targets:
            targets.append((15, 15))

        for local_x, local_z in targets:
            bx = region_x + local_x * chunk_size
            by = region_y + local_z * chunk_size
            line_color = "#FFFFFF33" if block_px >= 4 else "#FFFFFF22"
            for i in range(1, 16):
                pos = i * block_px
                shapes.append(
                    cv.Line(
                        bx + pos,
                        by,
                        bx + pos,
                        by + chunk_size,
                        paint=ft.Paint(color=line_color, stroke_width=0.5),
                    )
                )
                shapes.append(
                    cv.Line(
                        bx,
                        by + pos,
                        bx + chunk_size,
                        by + pos,
                        paint=ft.Paint(color=line_color, stroke_width=0.5),
                    )
                )
            if self._show_coordinates and block_px >= 6:
                cx = rx * 32 + local_x
                cz = rz * 32 + local_z
                shapes.append(
                    cv.Text(
                        x=bx + 2,
                        y=by + 2,
                        value=f"{cx * 16},{cz * 16}",
                        style=ft.TextStyle(size=10, color="#FFF59D"),
                    )
                )
            if block_px >= 4:
                for bz in range(16):
                    for bx_i in range(16):
                        world_bx = (rx * 32 + local_x) * 16 + bx_i
                        world_bz = (rz * 32 + local_z) * 16 + bz
                        self._block_bounds[(world_bx, world_bz)] = (
                            bx + bx_i * block_px,
                            by + bz * block_px,
                            block_px,
                            block_px,
                        )
        return shapes

    def _build_origin_marker(self, x: float, y: float) -> List[cv.Shape]:
        width = self.width or 800
        height = self.height or 600
        return [
            cv.Rect(x, 0, 2, height, paint=ft.Paint(color=self.ORIGIN_COLOR)),
            cv.Rect(0, y, width, 2, paint=ft.Paint(color=self.ORIGIN_COLOR)),
        ]

    def _build_info_overlay(self) -> List[cv.Shape]:
        shapes: List[cv.Shape] = []
        width = self.width or 800
        height = self.height or 600
        title = (
            f"{get_mode_title(self._display_mode)} · "
            f"{self._view_level_title()} · {self._scale:.1f}x"
        )
        shapes.append(cv.Rect(10, 10, 260, 26, paint=ft.Paint(color="#00000099")))
        shapes.append(
            cv.Text(
                x=15,
                y=15,
                value=title,
                style=ft.TextStyle(size=12, color="#D7CCC8"),
            )
        )
        shapes.append(cv.Rect(10, 42, 310, 24, paint=ft.Paint(color="#00000066")))
        shapes.append(
            cv.Text(
                x=15,
                y=47,
                value="拖拽平移 · 滚轮缩放切层级 · 双击深入 · 右键返回",
                style=ft.TextStyle(size=11, color="#A5D6A7"),
            )
        )

        if self._service.is_scanning:
            progress = self._service.scan_progress
            shapes.append(
                cv.Rect(10, height - 34, 120, 24, paint=ft.Paint(color="#00000088"))
            )
            shapes.append(
                cv.Text(
                    x=15,
                    y=height - 29,
                    value=f"扫描中: {int(progress * 100)}%",
                    style=ft.TextStyle(size=12, color="#64B5F6"),
                )
            )

        if self._selected_cell:
            coord = self._selected_cell
            if self._selected_chunk is not None:
                cx, cz = self._selected_chunk
                prefix = "区块内" if self._view_level == "block" else "区块"
                info = (
                    f"{prefix} ({cx},{cz}) · "
                    f"{format_chunk_block_range(self._selected_chunk)}"
                )
            else:
                info = (
                    f"r.{coord[0]}.{coord[1]}.mca · "
                    f"{format_region_block_range(coord)}"
                )
            text_w = max(140, len(info) * 7 + 20)
            shapes.append(
                cv.Rect(
                    width - text_w - 10,
                    10,
                    text_w,
                    24,
                    paint=ft.Paint(color="#00000088"),
                )
            )
            shapes.append(
                cv.Text(
                    x=width - text_w - 5,
                    y=15,
                    value=info,
                    style=ft.TextStyle(size=12, color="#64B5F6"),
                )
            )
        return shapes

    def _view_level_title(self) -> str:
        return {
            "world": "世界",
            "region": "区域",
            "chunk": "区块",
            "block": "区块内",
        }.get(self._view_level, "世界")

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
                    pass

    def did_mount(self) -> None:
        super().did_mount()
        self._mounted = True
        self._service.set_tile_ready_callback(self._on_tile_ready)
        if self._needs_initial_draw:
            self._request_rebuild()
        if self._service.is_scanning:
            self._start_update_loop()

    def did_unmount(self) -> None:
        self._mounted = False
        self._zoom_anim_active = False
        try:
            if self._zoom_anim_timer is not None:
                self._zoom_anim_timer.cancel()
        except Exception:
            pass
        self._zoom_anim_timer = None
        self._cancel_rebuild_timer()
        self._stop_update_loop()
        # Drop callback so worker threads do not touch a dead view.
        try:
            if getattr(self._service, "_tile_ready_callback", None) is self._on_tile_ready:
                self._service.set_tile_ready_callback(None)
        except Exception:
            pass
        super_did_unmount = getattr(super(), "did_unmount", None)
        if super_did_unmount:
            super_did_unmount()

    def _schedule_task(self, coro: Any) -> Optional[ScheduledTask]:
        """Schedule a coroutine on the UI event loop when possible."""
        try:
            return asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            pass

        page = cast(Optional[ft.Page], self.page)
        if page is not None:
            try:
                async def _runner() -> Any:
                    return await coro

                return page.run_task(_runner)
            except Exception:
                pass

        # Last resort: background loop (scan-only; UI updates still go via run_on_ui).
        def _run_in_thread() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()

        threading.Thread(target=_run_in_thread, daemon=True).start()
        return None

    def _start_update_loop(self) -> None:
        if self._update_task is None or self._update_task.done():
            self._update_task = self._schedule_task(self._update_loop())

    def _stop_update_loop(self) -> None:
        if self._update_task and not self._update_task.done():
            self._update_task.cancel()
        self._update_task = None

    # ------------------------------------------------------------------ public API (region_tab)
    def start_scan(self, region_dir: str) -> None:
        self._schedule_task(self._service.start_silent_scan(region_dir))
        self._start_update_loop()

    def refresh(self) -> None:
        self._viewport.reset()
        self._view_level = "world"
        self._request_rebuild()

    def reset_view(self) -> None:
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
            min_fit_scale=0.2,
            max_fit_scale=8.0,
        )
        self._viewport.apply(target)
        self._view_level = view_level_from_scale(self._scale)
        self._request_rebuild()

    def resize_map(self, width: int, height: int, *, refit: bool = False) -> None:
        width = max(120, int(width))
        height = max(100, int(height))
        if self.width == width and self.height == height and not refit:
            return
        self.width = width
        self.height = height
        self._canvas.width = width
        self._canvas.height = height
        self._gesture.width = width
        self._gesture.height = height
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
        except Exception:
            return
        if w < 80 or h < 80:
            return
        self.resize_map(w, h)

    def toggle_coordinates(self) -> bool:
        self._show_coordinates = not self._show_coordinates
        self._request_rebuild()
        return self._show_coordinates

    def toggle_empty_regions(self) -> bool:
        self._show_empty_regions = not self._show_empty_regions
        self._request_rebuild()
        return self._show_empty_regions

    def set_display_mode(self, mode: str) -> None:
        if mode not in {"activity", "topview", "biome", "structure"}:
            return
        self._display_mode = mode
        self._use_topview = mode in {"activity", "topview"}
        self._request_rebuild()

    def get_display_mode(self) -> str:
        return self._display_mode

    def set_detail_level(self, level: str) -> None:
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
        return self._view_level

    def zoom_in(self) -> None:
        cx = (self.width or 800) / 2
        cy = (self.height or 600) / 2
        self._zoom_pivot_x = cx
        self._zoom_pivot_y = cy
        self._animate_zoom_toward(1.22, cx, cy)

    def zoom_out(self) -> None:
        cx = (self.width or 800) / 2
        cy = (self.height or 600) / 2
        self._zoom_pivot_x = cx
        self._zoom_pivot_y = cy
        self._animate_zoom_toward(0.82, cx, cy)

    def _animate_zoom_toward(
        self,
        factor: float,
        pivot_x: float,
        pivot_y: float,
        duration: float = 0.16,
    ) -> None:
        """Ease-out zoom around a screen-space pivot (pointer or view center)."""
        # Use current *target* if an animation is already running so rapid
        # wheel ticks compound instead of fighting the in-flight frame.
        base = (
            self._zoom_anim_target
            if self._zoom_anim_active
            else self._viewport.current_target
        )
        target = self._viewport.zoom_about(
            factor,
            pivot_x,
            pivot_y,
            base,
        )
        if abs(target.scale - base.scale) < 1e-6:
            return
        self._zoom_pivot_x = pivot_x
        self._zoom_pivot_y = pivot_y
        self._animate_camera_to(
            target.scale,
            target.offset_x,
            target.offset_y,
            duration=duration,
        )

    def _animate_camera_to(
        self,
        target_scale: float,
        target_offset_x: float,
        target_offset_y: float,
        duration: float = 0.22,
    ) -> None:
        """Animate scale + offset toward an absolute camera target."""
        self._zoom_anim_start = self._viewport.current_target
        self._zoom_anim_target = ViewportTarget(
            max(self.MIN_SCALE, min(self.MAX_SCALE, float(target_scale))),
            float(target_offset_x),
            float(target_offset_y),
        )
        self._zoom_anim_t0 = time.monotonic()
        self._zoom_anim_duration = max(0.05, duration)
        self._zoom_anim_active = True
        self._kick_zoom_anim()

    def _kick_zoom_anim(self) -> None:
        try:
            if self._zoom_anim_timer is not None:
                self._zoom_anim_timer.cancel()
        except Exception:
            pass

        def _tick() -> None:
            if not self._zoom_anim_active or not self._mounted:
                return
            elapsed = time.monotonic() - self._zoom_anim_t0
            t = min(1.0, elapsed / self._zoom_anim_duration)
            # ease-out cubic
            ease = 1.0 - (1.0 - t) ** 3
            self._viewport.apply(
                self._zoom_anim_start.interpolate(self._zoom_anim_target, ease)
            )
            try:
                self._sync_view_level_from_scale(notify=False)
            except Exception:
                pass
            self._request_rebuild()
            if t < 1.0:
                self._zoom_anim_timer = threading.Timer(1.0 / 60.0, _tick)
                self._zoom_anim_timer.daemon = True
                self._zoom_anim_timer.start()
            else:
                self._zoom_anim_active = False
                self._zoom_anim_timer = None
                # Snap exactly to target
                self._viewport.apply(self._zoom_anim_target)
                try:
                    self._sync_view_level_from_scale(notify=True)
                except Exception:
                    pass
                self._request_rebuild()

        self._zoom_anim_timer = threading.Timer(0.0, _tick)
        self._zoom_anim_timer.daemon = True
        self._zoom_anim_timer.start()

    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        return self._selected_cell
