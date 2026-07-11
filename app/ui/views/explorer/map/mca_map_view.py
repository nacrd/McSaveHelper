"""MCA region map view — minimal interactive map display.

Draws region files (r.x.z.mca) as a colored grid on Flet Canvas.
Supports pan, zoom, click-to-select, and progressive scan updates.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import flet as ft

try:
    import flet.canvas as cv
except ImportError as exc:  # pragma: no cover
    raise ImportError("flet.canvas is not available in this Flet version") from exc

from app.services.region_map_service import RegionMapService, get_region_map_service
from app.ui.utils import run_on_ui
from app.ui.views.explorer.map.color_schemes import (
    BACKGROUND_COLOR,
    EMPTY_REGION_COLOR,
    ORIGIN_COLOR,
    SELECTED_BORDER_COLOR,
    get_mode_title,
    get_region_color,
    get_region_value_label,
)
from app.ui.views.explorer.map.topview_renderer import (
    DEFAULT_TILE_SIZE,
    DETAIL_TILE_SIZE,
)


MapSelectionCallback = Callable[
    [Optional[Tuple[int, int]], Optional[int], Optional[Dict[str, Any]]], None
]


class McaMapView(ft.Container):
    """Minimal MCA region map (presence grid, not size heatmap)."""

    BACKGROUND_COLOR = BACKGROUND_COLOR
    EMPTY_REGION_COLOR = EMPTY_REGION_COLOR
    ORIGIN_COLOR = ORIGIN_COLOR
    CELL_SIZE = 32
    CELL_GAP = 2

    def __init__(
        self,
        map_service: Optional[RegionMapService] = None,
        on_selection_changed: Optional[MapSelectionCallback] = None,
        width: int = 700,
        height: int = 450,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self._service = map_service or get_region_map_service()
        self._on_selection_changed = on_selection_changed

        self._offset_x = 0.0
        self._offset_y = 0.0
        self._scale = 1.0
        self._show_coordinates = True
        self._show_empty_regions = False
        self._display_mode = "topview"
        self._detail_level = "region"
        self._use_topview = True

        self._selected_cell: Optional[Tuple[int, int]] = None
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._cached_stats: Optional[Dict[str, Any]] = None
        # base64 cache for canvas Image.src (derived from service PNG bytes)
        self._tile_src_cache: Dict[Tuple[int, int], str] = {}
        self._tile_src_generation = -1

        self._last_x = 0.0
        self._last_y = 0.0
        self._needs_initial_draw = True
        self._update_task: Optional[asyncio.Task[Any]] = None
        self._last_drawn_count = -1
        self._mounted = False

        self._rebuild_pending = False
        self._rebuild_timer: Optional[threading.Timer] = None
        self._last_rebuild_ts = 0.0
        self._min_rebuild_interval = 1.0 / 60.0
        # Smooth zoom animation state (world-space pivot + ease-out)
        self._zoom_anim_timer: Optional[threading.Timer] = None
        self._zoom_anim_active = False
        self._zoom_anim_start_scale = 1.0
        self._zoom_anim_target_scale = 1.0
        self._zoom_anim_start_offset_x = 0.0
        self._zoom_anim_start_offset_y = 0.0
        self._zoom_anim_target_offset_x = 0.0
        self._zoom_anim_target_offset_y = 0.0
        self._zoom_anim_t0 = 0.0
        self._zoom_anim_duration = 0.16

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
        run_on_ui(page, self._rebuild_canvas_safe)

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
        self._offset_x += dx
        self._offset_y += dy
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y
        self._schedule_rebuild()

    def _on_tap(self, e: ft.TapEvent) -> None:
        tap_x = e.local_position.x
        tap_y = e.local_position.y
        for coord, bounds in self._cell_bounds.items():
            bx, by, bw, bh = bounds
            if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                if coord not in self._current_data:
                    break
                self._selected_cell = coord
                size = self._current_data[coord]
                if self._on_selection_changed:
                    self._on_selection_changed(coord, size, {"level": "region"})
                # Local zoom into the clicked region + request hi-res tile.
                self._focus_region(coord, animate=True)
                break

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

        cell_pitch = float(self.CELL_SIZE + self.CELL_GAP)
        # Desired on-screen size of one region cell.
        desired = min(view_w, view_h) * max(0.35, min(0.95, target_fill))
        target_scale = max(0.35, min(12.0, desired / self.CELL_SIZE))

        # World-space center of the region cell.
        world_cx = (coord[0] + 0.5) * cell_pitch
        world_cz = (coord[1] + 0.5) * cell_pitch
        target_ox = view_w / 2.0 - world_cx * target_scale
        target_oy = view_h / 2.0 - world_cz * target_scale

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
                target_scale, target_ox, target_oy, duration=0.28
            )
        else:
            self._scale = target_scale
            self._offset_x = target_ox
            self._offset_y = target_oy
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
        self._animate_zoom_toward(zoom_factor, float(pointer_x), float(pointer_y))

    # ------------------------------------------------------------------ draw
    def _rebuild_canvas(self) -> None:
        self._current_data = self._service.get_all_data()
        self._cached_stats = self._service.get_statistics()
        shapes: List[cv.Shape] = list(self._empty_shapes())
        view_w = self.width or 800
        view_h = self.height or 600

        if not self._current_data:
            shapes.append(
                cv.Text(
                    x=view_w / 2 - 90,
                    y=view_h / 2 - 30,
                    value="🗺️",
                    style=ft.TextStyle(size=48, color="#888888"),
                )
            )
            shapes.append(
                cv.Text(
                    x=view_w / 2 - 95,
                    y=view_h / 2 + 30,
                    value="设置当前存档后显示区域地图",
                    style=ft.TextStyle(size=16, color="#CCCCCC"),
                )
            )
            shapes.extend(self._build_info_overlay())
            self._apply_shapes(shapes)
            return

        coords = list(self._current_data.keys())
        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_z = min(c[1] for c in coords)
        max_z = max(c[1] for c in coords)

        cell_pitch = self.CELL_SIZE + self.CELL_GAP
        world_w = (max_x - min_x + 1) * cell_pitch
        world_h = (max_z - min_z + 1) * cell_pitch

        if self._scale == 1.0 and self._offset_x == 0 and self._offset_y == 0:
            # Initial fit: center data bbox in the current viewport.
            pad = 0.78
            scale_x = view_w / world_w * pad
            scale_y = view_h / world_h * pad
            self._scale = max(0.35, min(scale_x, scale_y, 3.0))
            center_x = (min_x + max_x) / 2.0
            center_z = (min_z + max_z) / 2.0
            self._offset_x = view_w / 2.0 - center_x * cell_pitch * self._scale
            self._offset_y = view_h / 2.0 - center_z * cell_pitch * self._scale

        self._cell_bounds.clear()
        origin_x = self._offset_x
        origin_y = self._offset_y
        shapes.extend(self._build_origin_marker(origin_x, origin_y))

        margin = cell_pitch
        pitch_scaled = cell_pitch * self._scale
        # Guard against degenerate scale that would explode the draw loop.
        if pitch_scaled <= 1e-6:
            self._apply_shapes(shapes)
            return
        vis_min_x = int(math.floor((0 - margin - self._offset_x) / pitch_scaled))
        vis_max_x = int(math.ceil((view_w + margin - self._offset_x) / pitch_scaled))
        vis_min_z = int(math.floor((0 - margin - self._offset_y) / pitch_scaled))
        vis_max_z = int(math.ceil((view_h + margin - self._offset_y) / pitch_scaled))
        draw_min_x = max(min_x, vis_min_x)
        draw_max_x = min(max_x, vis_max_x)
        draw_min_z = max(min_z, vis_min_z)
        draw_max_z = min(max_z, vis_max_z)

        missing: List[Tuple[int, int]] = []
        for z in range(draw_min_z, draw_max_z + 1):
            for x in range(draw_min_x, draw_max_x + 1):
                screen_x = x * cell_pitch * self._scale + self._offset_x
                screen_y = z * cell_pitch * self._scale + self._offset_y
                cell_size = self.CELL_SIZE * self._scale
                if (
                    screen_x + cell_size < 0
                    or screen_x > view_w
                    or screen_y + cell_size < 0
                    or screen_y > view_h
                ):
                    continue

                coord = (x, z)
                self._cell_bounds[coord] = (screen_x, screen_y, cell_size, cell_size)
                if coord in self._current_data:
                    size = self._current_data[coord]
                    color = get_region_color(size, self._cached_stats or {})
                    shapes.extend(
                        self._build_region_cell(
                            screen_x, screen_y, cell_size, color, coord, size
                        )
                    )
                    if self._use_topview and not self._service.has_topview_tile(coord):
                        missing.append(coord)
                elif self._show_empty_regions:
                    shapes.append(
                        cv.Rect(
                            screen_x,
                            screen_y,
                            cell_size,
                            cell_size,
                            paint=ft.Paint(
                                color=self.EMPTY_REGION_COLOR,
                                style=ft.PaintingStyle.STROKE,
                                stroke_width=0.5,
                            ),
                        )
                    )

        if missing:
            self._service.request_topview_tiles(
                missing, tile_size=DEFAULT_TILE_SIZE
            )
        # While zoomed in, upgrade selected/nearby tiles to detail resolution.
        if self._use_topview and self._selected_cell is not None and self._scale >= 2.2:
            sel = self._selected_cell
            upgrade = [
                (sel[0] + dx, sel[1] + dz)
                for dz in (-1, 0, 1)
                for dx in (-1, 0, 1)
                if (sel[0] + dx, sel[1] + dz) in self._current_data
            ]
            need = [
                c for c in upgrade
                if not self._service.has_topview_tile(c, min_size=DETAIL_TILE_SIZE)
            ]
            if need:
                try:
                    self._service.request_topview_tiles(
                        need,
                        tile_size=DETAIL_TILE_SIZE,
                        force=True,
                        priority=True,
                    )
                except TypeError:
                    self._service.request_topview_tiles(
                        need, tile_size=DETAIL_TILE_SIZE
                    )

        shapes.extend(self._build_info_overlay())
        self._apply_shapes(shapes)
        self._needs_initial_draw = False

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
        if self._show_coordinates and size >= 22:
            shapes.append(
                cv.Text(
                    x=x + 4,
                    y=y + 5,
                    value=f"{coord[0]},{coord[1]}",
                    style=ft.TextStyle(
                        size=9 if size < 42 else 10,
                        color="#FFFFFF" if tile_src else "#F5F5DC",
                    ),
                )
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
        title = f"{get_mode_title(self._display_mode)} · 缩放 {self._scale:.1f}x"
        shapes.append(cv.Rect(10, 10, 200, 26, paint=ft.Paint(color="#00000099")))
        shapes.append(
            cv.Text(
                x=15,
                y=15,
                value=title,
                style=ft.TextStyle(size=12, color="#D7CCC8"),
            )
        )
        shapes.append(cv.Rect(10, 42, 200, 24, paint=ft.Paint(color="#00000066")))
        shapes.append(
            cv.Text(
                x=15,
                y=47,
                value="拖拽平移 · 滚轮缩放 · 点击区域",
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
            size = self._current_data.get(coord, 0)
            meta = self._service.get_region_meta(coord)
            info = get_region_value_label(
                self._display_mode, coord, size, meta, self._cached_stats or {}
            )
            text_w = max(120, len(info) * 7 + 20)
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
                run_on_ui(page, self._on_selection_changed, None, None, None)
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

    def _schedule_task(self, coro: Any) -> Optional[asyncio.Task[Any]]:
        """Schedule a coroutine on the UI event loop when possible."""
        try:
            return asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            pass

        page = self.page
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
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._request_rebuild()

    def reset_view(self) -> None:
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._selected_cell = None
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
            self._scale = 1.0
            self._offset_x = 0.0
            self._offset_y = 0.0
            self._request_rebuild()
            return

        coords = list(data.keys())
        min_x = min(c[0] for c in coords)
        max_x = max(c[0] for c in coords)
        min_z = min(c[1] for c in coords)
        max_z = max(c[1] for c in coords)
        cell_pitch = self.CELL_SIZE + self.CELL_GAP
        world_w = max(cell_pitch, (max_x - min_x + 1) * cell_pitch)
        world_h = max(cell_pitch, (max_z - min_z + 1) * cell_pitch)

        pad = max(0.2, min(1.0, float(padding)))
        scale_x = view_w / world_w * pad
        scale_y = view_h / world_h * pad
        self._scale = max(0.2, min(scale_x, scale_y, 8.0))

        # Center the data bounding box (not just the world origin).
        center_x = (min_x + max_x) / 2.0
        center_z = (min_z + max_z) / 2.0
        self._offset_x = view_w / 2.0 - center_x * cell_pitch * self._scale
        self._offset_y = view_h / 2.0 - center_z * cell_pitch * self._scale
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
        # v1: region-level only
        if level not in {"auto", "region", "chunk"}:
            return
        self._detail_level = "region"
        self._request_rebuild()

    def get_detail_level(self) -> str:
        return self._detail_level

    def zoom_in(self) -> None:
        cx = (self.width or 800) / 2
        cy = (self.height or 600) / 2
        self._animate_zoom_toward(1.22, cx, cy)

    def zoom_out(self) -> None:
        cx = (self.width or 800) / 2
        cy = (self.height or 600) / 2
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
        base_scale = (
            self._zoom_anim_target_scale if self._zoom_anim_active else self._scale
        )
        base_ox = (
            self._zoom_anim_target_offset_x if self._zoom_anim_active else self._offset_x
        )
        base_oy = (
            self._zoom_anim_target_offset_y if self._zoom_anim_active else self._offset_y
        )
        new_scale = max(0.1, min(12.0, base_scale * factor))
        if abs(new_scale - base_scale) < 1e-6:
            return
        world_x = (pivot_x - base_ox) / base_scale if base_scale else 0.0
        world_y = (pivot_y - base_oy) / base_scale if base_scale else 0.0
        target_ox = pivot_x - world_x * new_scale
        target_oy = pivot_y - world_y * new_scale
        self._animate_camera_to(new_scale, target_ox, target_oy, duration=duration)

    def _animate_camera_to(
        self,
        target_scale: float,
        target_offset_x: float,
        target_offset_y: float,
        duration: float = 0.22,
    ) -> None:
        """Animate scale + offset toward an absolute camera target."""
        self._zoom_anim_start_scale = self._scale
        self._zoom_anim_start_offset_x = self._offset_x
        self._zoom_anim_start_offset_y = self._offset_y
        self._zoom_anim_target_scale = max(0.1, min(12.0, float(target_scale)))
        self._zoom_anim_target_offset_x = float(target_offset_x)
        self._zoom_anim_target_offset_y = float(target_offset_y)
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
            s0 = self._zoom_anim_start_scale
            s1 = self._zoom_anim_target_scale
            self._scale = s0 + (s1 - s0) * ease
            self._offset_x = (
                self._zoom_anim_start_offset_x
                + (self._zoom_anim_target_offset_x - self._zoom_anim_start_offset_x) * ease
            )
            self._offset_y = (
                self._zoom_anim_start_offset_y
                + (self._zoom_anim_target_offset_y - self._zoom_anim_start_offset_y) * ease
            )
            self._request_rebuild()
            if t < 1.0:
                self._zoom_anim_timer = threading.Timer(1.0 / 60.0, _tick)
                self._zoom_anim_timer.daemon = True
                self._zoom_anim_timer.start()
            else:
                self._zoom_anim_active = False
                self._zoom_anim_timer = None
                # Snap exactly to target
                self._scale = self._zoom_anim_target_scale
                self._offset_x = self._zoom_anim_target_offset_x
                self._offset_y = self._zoom_anim_target_offset_y
                self._request_rebuild()

        self._zoom_anim_timer = threading.Timer(0.0, _tick)
        self._zoom_anim_timer.daemon = True
        self._zoom_anim_timer.start()

    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        return self._selected_cell
