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
    HIRES_TILE_SIZE,
    PREVIEW_TILE_SIZE,
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
        self._selected_chunk: Optional[Tuple[int, int]] = None  # world chunk (cx, cz)
        self._view_level: str = "world"  # world | region | chunk
        self._current_data: Dict[Tuple[int, int], int] = {}
        self._cell_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._chunk_bounds: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        self._cached_stats: Optional[Dict[str, Any]] = None
        # base64 cache for canvas Image.src (derived from service PNG bytes)
        self._tile_src_cache: Dict[Any, str] = {}
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
        # Cap interactive redraws (~20fps). Full 60fps canvas rebuild freezes UI.
        self._min_rebuild_interval = 1.0 / 20.0
        # True while panning / zoom-animating: skip tile fetches & heavy overlays.
        self._camera_busy = False
        self._idle_tile_timer: Optional[threading.Timer] = None
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

    def _on_tile_ready(self, coord: Tuple[int, int]) -> None:
        """Called from a worker thread when a topview PNG is cached."""
        try:
            if self._camera_busy or self._zoom_anim_active:
                self._schedule_idle_tile_pass(0.12)
                return
            if coord in self._current_data or not self._current_data:
                self._schedule_rebuild()
        except Exception:
            pass

    def _tile_src(self, coord: Tuple[int, int]) -> Optional[str]:
        """Return base64 PNG for coord, caching decoded form for canvas.

        Cache key includes rendered tile size so progressive upgrades
        (16->32->64->128) invalidate the previous base64 payload.
        """
        import base64

        generation = self._service.get_topview_generation()
        if generation != self._tile_src_generation:
            self._tile_src_cache.clear()
            self._tile_src_generation = generation
        try:
            tile_size = int(self._service.get_topview_tile_size(coord) or 0)
        except Exception:
            tile_size = 0
        cache_key = (coord, tile_size)
        cached = self._tile_src_cache.get(cache_key)  # type: ignore[arg-type]
        if cached is not None:
            return cached
        raw = self._service.get_topview_tile(coord)
        if not raw:
            return None
        src = base64.b64encode(raw).decode("ascii")
        # Drop older size variants for this coord to bound memory.
        for k in list(self._tile_src_cache.keys()):
            if isinstance(k, tuple) and k and k[0] == coord:
                self._tile_src_cache.pop(k, None)
        self._tile_src_cache[cache_key] = src  # type: ignore[index]
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

    def _rebuild_now(self) -> None:
        """Synchronous rebuild for gesture handlers already on the UI thread.

        Do NOT route pan/scroll through run_on_ui — that queues async work and
        makes the map lag behind the finger (and can flash).
        """
        if not self._mounted:
            return
        try:
            self._rebuild_canvas()
        except Exception:
            pass

    def _schedule_rebuild(self) -> None:
        """Rate-limit rebuilds from background threads (tile-ready, timers)."""
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

    def _schedule_interactive_redraw(self) -> None:
        """Rate-limited *direct* redraw for pan/zoom (already on UI thread)."""
        now = time.monotonic()
        # ~15fps during drag is enough; fewer Image/shape rebuilds = less flicker.
        if now - self._last_rebuild_ts < (1.0 / 15.0):
            return
        self._last_rebuild_ts = now
        self._rebuild_now()

    def _cancel_rebuild_timer(self) -> None:
        try:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()
        except Exception:
            pass
        self._rebuild_timer = None
        self._rebuild_pending = False
        try:
            if getattr(self, "_idle_tile_timer", None) is not None:
                self._idle_tile_timer.cancel()
        except Exception:
            pass
        self._idle_tile_timer = None

    def _schedule_idle_tile_pass(self, delay: float = 0.18) -> None:
        """After camera settles, fetch/upgrade tiles once (not every pan frame)."""
        try:
            if self._idle_tile_timer is not None:
                self._idle_tile_timer.cancel()
        except Exception:
            pass

        def _fire() -> None:
            self._idle_tile_timer = None
            self._camera_busy = False
            try:
                self._request_rebuild()
            except Exception:
                pass

        self._idle_tile_timer = threading.Timer(max(0.05, delay), _fire)
        self._idle_tile_timer.daemon = True
        self._idle_tile_timer.start()

    # ------------------------------------------------------------------ gestures
    def _on_pan_start(self, e: ft.DragStartEvent) -> None:
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y
        self._camera_busy = True

    def _on_pan_update(self, e: ft.DragUpdateEvent) -> None:
        dx = e.local_position.x - self._last_x
        dy = e.local_position.y - self._last_y
        self._offset_x += dx
        self._offset_y += dy
        self._last_x = e.local_position.x
        self._last_y = e.local_position.y
        self._camera_busy = True
        # Direct UI-thread redraw (no run_on_ui queue lag).
        self._schedule_interactive_redraw()
        self._schedule_idle_tile_pass()

    def _on_tap(self, e: ft.TapEvent) -> None:
        tap_x = e.local_position.x
        tap_y = e.local_position.y

        # Chunk-level selection when deeply zoomed into a region.
        if self._view_level == "chunk" and self._chunk_bounds:
            for chunk_coord, bounds in self._chunk_bounds.items():
                bx, by, bw, bh = bounds
                if bx <= tap_x <= bx + bw and by <= tap_y <= by + bh:
                    self._selected_chunk = chunk_coord
                    region = (chunk_coord[0] // 32, chunk_coord[1] // 32)
                    self._selected_cell = region
                    size = self._current_data.get(region, 0)
                    if self._on_selection_changed:
                        self._on_selection_changed(
                            region,
                            size,
                            {
                                "level": "chunk",
                                "chunk_coord": chunk_coord,
                                "block_range": self._chunk_block_range(chunk_coord),
                            },
                        )
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
                            "block_range": self._region_block_range(coord),
                        },
                    )
                # Single click: local zoom into the region (not full chunk level).
                self._focus_region(coord, animate=True, target_fill=0.72)
                self._view_level = "region"
                break

    def _on_double_tap(self, e: Any) -> None:
        """Double-click: zoom to chunk level inside the hit region."""
        tap_x = getattr(getattr(e, "local_position", None), "x", None)
        tap_y = getattr(getattr(e, "local_position", None), "y", None)
        if tap_x is None or tap_y is None:
            # Some Flet versions only provide local_x/local_y on double tap.
            tap_x = getattr(e, "local_x", (self.width or 800) / 2)
            tap_y = getattr(e, "local_y", (self.height or 600) / 2)

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
                    "block_range": self._region_block_range(hit),
                },
            )
        # Stronger zoom so one region fills almost the whole view → chunk grid readable.
        self._focus_region(hit, animate=True, target_fill=0.92)
        self._view_level = "chunk"
        # Ensure hi-res tile for chunk inspection.
        if self._use_topview:
            self._request_tiles_progressive(
                [hit], desired=HIRES_TILE_SIZE, priority=True
            )

    def _on_secondary_tap(self, e: Any) -> None:
        """Right-click: step back overview (chunk→region→world)."""
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
                        "block_range": self._region_block_range(self._selected_cell),
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

    def _region_block_range(self, coord: Tuple[int, int]) -> str:
        rx, rz = coord
        return f"X {rx * 512}~{rx * 512 + 511}, Z {rz * 512}~{rz * 512 + 511}"

    def _chunk_block_range(self, chunk_coord: Tuple[int, int]) -> str:
        cx, cz = chunk_coord
        return f"X {cx * 16}~{cx * 16 + 15}, Z {cz * 16}~{cz * 16 + 15}"

    def _coord_label_for_region(self, coord: Tuple[int, int], cell_size: float) -> str:
        """Progressively reveal real game coordinates as the user zooms in.

        - far: region index ``rx,rz``
        - mid: block range of the region (two lines when space allows)
        - near/chunk: center block coords (actual game X/Z)
        """
        rx, rz = coord
        if self._view_level == "chunk" or self._scale >= 6.0 or cell_size >= 180:
            bx = rx * 512 + 256
            bz = rz * 512 + 256
            return f"{bx}, {bz}"
        if self._scale >= 2.4 or cell_size >= 70:
            x0, x1 = rx * 512, rx * 512 + 511
            z0, z1 = rz * 512, rz * 512 + 511
            if cell_size >= 90:
                return f"X{x0}~{x1}\nZ{z0}~{z1}"
            return f"{x0}~{x1}"
        return f"{rx},{rz}"

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
        target_scale = max(0.35, min(18.0, desired / self.CELL_SIZE))

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
            self._request_tiles_progressive(
                neighbors, desired=self._desired_tile_size(), priority=True
            )

        if animate:
            self._animate_camera_to(
                target_scale, target_ox, target_oy, duration=0.16
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


    def _desired_tile_size(self) -> int:
        """Target tile resolution for current camera / view level."""
        if self._view_level == "chunk" or self._scale >= 5.5:
            return HIRES_TILE_SIZE
        if self._view_level == "region" or self._scale >= 2.2:
            return DETAIL_TILE_SIZE
        if self._scale >= 1.2:
            return DEFAULT_TILE_SIZE
        return DEFAULT_TILE_SIZE

    def _next_tile_size(self, current: int, desired: int) -> int:
        """Step up one rung on 16->32->64->128 so first paint stays cheap."""
        ladder = (PREVIEW_TILE_SIZE, DEFAULT_TILE_SIZE, DETAIL_TILE_SIZE, HIRES_TILE_SIZE)
        desired = max(PREVIEW_TILE_SIZE, int(desired))
        for s in reversed(ladder):
            if desired >= s:
                desired = s
                break
        if current <= 0:
            return PREVIEW_TILE_SIZE
        if current >= desired:
            return desired
        for s in ladder:
            if s > current:
                return min(s, desired)
        return desired

    def _request_tiles_progressive(
        self,
        coords: list,
        *,
        desired: int | None = None,
        priority: bool = False,
    ) -> None:
        if not coords or not self._use_topview:
            return
        desired_i = int(desired if desired is not None else self._desired_tile_size())
        previews: list = []
        upgrades: list = []
        for coord in coords:
            have = 0
            try:
                have = int(self._service.get_topview_tile_size(coord) or 0)
            except Exception:
                have = 0 if not self._service.has_topview_tile(coord) else DEFAULT_TILE_SIZE
            if have <= 0:
                previews.append(coord)
            elif have < desired_i:
                upgrades.append((coord, self._next_tile_size(have, desired_i)))

        if previews:
            try:
                self._service.request_topview_tiles(
                    previews, tile_size=PREVIEW_TILE_SIZE, priority=priority
                )
            except TypeError:
                self._service.request_topview_tiles(previews, tile_size=PREVIEW_TILE_SIZE)

        by_size: dict = {}
        for coord, size in upgrades:
            by_size.setdefault(size, []).append(coord)
        for size, group in by_size.items():
            try:
                self._service.request_topview_tiles(
                    group, tile_size=size, force=True, priority=priority
                )
            except TypeError:
                self._service.request_topview_tiles(group, tile_size=size)

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
        self._chunk_bounds.clear()
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
        camera_busy = bool(self._camera_busy or self._zoom_anim_active)
        draw_chunk_grid = (
            not camera_busy
            and (self._view_level == "chunk" or self._scale >= 6.5)
        )
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
                    if draw_chunk_grid and cell_size >= 160:
                        shapes.extend(
                            self._build_chunk_grid(
                                screen_x, screen_y, cell_size, coord
                            )
                        )
                    if self._use_topview and not camera_busy:
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

        if not camera_busy:
            if missing:
                self._request_tiles_progressive(
                    missing[:80], desired=self._desired_tile_size()
                )
            if self._use_topview and self._selected_cell is not None:
                sel = self._selected_cell
                hot = [
                    (sel[0] + dx, sel[1] + dz)
                    for dz in (-1, 0, 1)
                    for dx in (-1, 0, 1)
                    if (sel[0] + dx, sel[1] + dz) in self._current_data
                ]
                self._request_tiles_progressive(
                    hot,
                    desired=self._desired_tile_size(),
                    priority=True,
                )

        shapes.extend(self._build_info_overlay())
        self._apply_shapes(shapes)
        self._needs_initial_draw = False

    def _apply_shapes(self, shapes: List[cv.Shape]) -> None:
        if not self._mounted:
            return
        # Prefer in-place update; avoid full list churn flicker when possible.
        try:
            self._canvas.shapes = shapes
            self._canvas.update()
        except RuntimeError:
            pass
        except Exception:
            try:
                self._canvas.shapes = list(shapes)
                self._canvas.update()
            except Exception:
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
        # During pan/zoom: solid rect only. Rebuilding dozens of base64 Images
        # every frame causes flicker and multi-frame input lag.
        camera_busy = bool(self._camera_busy or self._zoom_anim_active)
        tile_src = None if camera_busy else (
            self._tile_src(coord) if self._use_topview else None
        )
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
            # Placeholder until topview tile is ready (or while camera moving)
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
        if (not camera_busy) and self._show_coordinates and size >= 22:
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
    ) -> List[cv.Shape]:
        """Draw 32×32 chunk mesh inside a region when zoomed in enough."""
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
                if self._show_coordinates and chunk_size >= 14:
                    # Game block coords of chunk origin.
                    shapes.append(
                        cv.Text(
                            x=bx + 1,
                            y=by + 1,
                            value=f"{cx * 16},{cz * 16}",
                            style=ft.TextStyle(size=8, color="#FFECB3"),
                        )
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
        title = f"{get_mode_title(self._display_mode)} · {self._view_level_title()} · {self._scale:.1f}x"
        shapes.append(cv.Rect(10, 10, 240, 26, paint=ft.Paint(color="#00000099")))
        shapes.append(
            cv.Text(
                x=15,
                y=15,
                value=title,
                style=ft.TextStyle(size=12, color="#D7CCC8"),
            )
        )
        shapes.append(cv.Rect(10, 42, 250, 24, paint=ft.Paint(color="#00000066")))
        shapes.append(
            cv.Text(
                x=15,
                y=47,
                value="拖拽平移 · 滚轮缩放 · 双击区块级 · 右键总览",
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
            if self._selected_chunk is not None:
                cx, cz = self._selected_chunk
                info = (
                    f"区块 ({cx},{cz}) · "
                    f"{self._chunk_block_range(self._selected_chunk)}"
                )
            else:
                info = (
                    f"r.{coord[0]}.{coord[1]}.mca · "
                    f"{self._region_block_range(coord)}"
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
        if level not in {"auto", "region", "chunk", "world"}:
            return
        if level == "auto":
            return
        self._detail_level = level
        self._view_level = "chunk" if level == "chunk" else (
            "region" if level == "region" else "world"
        )
        if self._view_level == "world":
            self._selected_chunk = None
            self.fit_to_view()
        elif self._view_level == "region" and self._selected_cell is not None:
            self._selected_chunk = None
            self._focus_region(self._selected_cell, animate=True, target_fill=0.72)
        elif self._view_level == "chunk" and self._selected_cell is not None:
            self._focus_region(self._selected_cell, animate=True, target_fill=0.92)
        else:
            self._request_rebuild()

    def get_detail_level(self) -> str:
        return self._view_level

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
        duration: float = 0.18,
    ) -> None:
        """Animate scale + offset toward an absolute camera target."""
        self._camera_busy = True
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
            # Timer thread → must hop to UI; rate-limited.
            self._schedule_rebuild()
            if t < 1.0:
                # ~15fps animation ticks — keeps UI responsive.
                self._zoom_anim_timer = threading.Timer(1.0 / 15.0, _tick)
                self._zoom_anim_timer.daemon = True
                self._zoom_anim_timer.start()
            else:
                self._zoom_anim_active = False
                self._zoom_anim_timer = None
                self._scale = self._zoom_anim_target_scale
                self._offset_x = self._zoom_anim_target_offset_x
                self._offset_y = self._zoom_anim_target_offset_y
                self._camera_busy = False
                # One full rebuild with tile fetch after camera stops.
                self._request_rebuild()

        self._zoom_anim_timer = threading.Timer(0.0, _tick)
        self._zoom_anim_timer.daemon = True
        self._zoom_anim_timer.start()

    def get_selected_cell(self) -> Optional[Tuple[int, int]]:
        return self._selected_cell
