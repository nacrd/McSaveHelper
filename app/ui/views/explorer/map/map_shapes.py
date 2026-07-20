"""Canvas shape builders for the MCA region map.

Keeps pure layout/label drawing out of the interactive Flet container.
"""
from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Optional, Tuple

import flet as ft

try:
    import flet.canvas as cv
except ImportError as exc:  # pragma: no cover
    raise ImportError("flet.canvas is not available in this Flet version") from exc

from app.ui.views.explorer.map.color_schemes import (
    EMPTY_REGION_COLOR,
    ORIGIN_COLOR,
    SELECTED_BORDER_COLOR,
    get_mode_title,
)
from core.mca.map_coordinates import (
    format_chunk_block_range,
    format_region_block_range,
)
from core.mca.viewport import MapViewLevel
from core.mca.map_models import MapMarker


Coord = Tuple[int, int]
ScreenRect = Tuple[float, float, float, float]
TileSource = Callable[[Coord], Optional[str]]
CoordLabel = Callable[[Coord, float], str]
BlockToScreen = Callable[[float, float], Tuple[float, float]]


def empty_background(
    width: float,
    height: float,
    color: str,
) -> List[cv.Shape]:
    return [cv.Rect(0, 0, width, height, paint=ft.Paint(color=color))]


def empty_state(view_w: float, view_h: float) -> List[cv.Shape]:
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


def empty_region(rect: ScreenRect, color: str = EMPTY_REGION_COLOR) -> cv.Rect:
    x, y, width, height = rect
    return cv.Rect(
        x,
        y,
        width,
        height,
        paint=ft.Paint(
            color=color,
            style=ft.PaintingStyle.STROKE,
            stroke_width=0.5,
        ),
    )


def origin_marker(
    x: float,
    y: float,
    width: float,
    height: float,
    color: str = ORIGIN_COLOR,
) -> List[cv.Shape]:
    return [
        cv.Rect(x, 0, 2, height, paint=ft.Paint(color=color)),
        cv.Rect(0, y, width, 2, paint=ft.Paint(color=color)),
    ]


def region_cell(
    x: float,
    y: float,
    size: float,
    color: str,
    coord: Coord,
    *,
    selected: bool,
    view_level: MapViewLevel,
    show_coordinates: bool,
    tile_src: Optional[str],
    coord_label: CoordLabel,
    value_label: Optional[str] = None,
) -> List[cv.Shape]:
    shapes: List[cv.Shape] = []
    if tile_src:
        shapes.append(
            cv.Image(
                src=tile_src,
                x=x,
                y=y,
                width=size,
                height=size,
                paint=ft.Paint(anti_alias=False),
            )
        )
    else:
        shapes.append(cv.Rect(x, y, size, size, paint=ft.Paint(color=color)))
    if selected:
        shapes.append(
            cv.Rect(
                x,
                y,
                size,
                size,
                paint=ft.Paint(
                    color=SELECTED_BORDER_COLOR,
                    style=ft.PaintingStyle.STROKE,
                    stroke_width=3,
                ),
            )
        )
    if show_coordinates and size >= 22 and view_level != "block":
        shapes.extend(
            _region_coord_labels(
                x,
                y,
                size,
                coord,
                tile_src=tile_src,
                coord_label=coord_label,
            )
        )
    if value_label and size >= 56 and view_level not in {"chunk", "block"}:
        # Metadata labels live in a separate lower strip so they never cover
        # the coordinate label or change the region cell dimensions.
        label = value_label.replace("\n", " ")[:38]
        shapes.append(
            cv.Text(
                x=x + 4,
                y=y + size - 15,
                value=label,
                style=ft.TextStyle(size=9, color="#FFF3C4"),
            )
        )
    return shapes


def _region_coord_labels(
    x: float,
    y: float,
    size: float,
    coord: Coord,
    *,
    tile_src: Optional[str],
    coord_label: CoordLabel,
) -> List[cv.Shape]:
    label = coord_label(coord, size)
    text_color = "#FFFFFF" if tile_src else "#F5F5DC"
    shapes: List[cv.Shape] = []
    if "\n" in label:
        for index, line in enumerate(label.split("\n")[:2]):
            shapes.append(
                cv.Text(
                    x=x + 4,
                    y=y + 4 + index * 12,
                    value=line,
                    style=ft.TextStyle(
                        size=9 if size < 70 else 10,
                        color=text_color,
                    ),
                )
            )
        return shapes
    shapes.append(
        cv.Text(
            x=x + 4,
            y=y + 5,
            value=label,
            style=ft.TextStyle(
                size=9 if size < 70 else 11,
                color=text_color,
            ),
        )
    )
    return shapes


def chunk_grid(
    x: float,
    y: float,
    size: float,
    region_coord: Coord,
    *,
    show_block_grid: bool,
    show_coordinates: bool,
    selected_chunk: Optional[Coord],
) -> Tuple[List[cv.Shape], Dict[Coord, ScreenRect], Dict[Coord, ScreenRect]]:
    shapes: List[cv.Shape] = []
    chunk_bounds: Dict[Coord, ScreenRect] = {}
    block_bounds: Dict[Coord, ScreenRect] = {}
    chunk_size = size / 32.0
    if chunk_size < 2.5:
        return shapes, chunk_bounds, block_bounds

    rx, rz = region_coord
    line_color = "#00000066" if chunk_size >= 4 else "#00000040"
    for index in range(1, 32):
        pos = index * chunk_size
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

    for local_z in range(32):
        for local_x in range(32):
            cx = rx * 32 + local_x
            cz = rz * 32 + local_z
            bx = x + local_x * chunk_size
            by = y + local_z * chunk_size
            chunk_bounds[(cx, cz)] = (bx, by, chunk_size, chunk_size)
            if show_coordinates and chunk_size >= 14 and not show_block_grid:
                shapes.append(
                    cv.Text(
                        x=bx + 1,
                        y=by + 1,
                        value=f"{cx * 16},{cz * 16}",
                        style=ft.TextStyle(size=8, color="#FFECB3"),
                    )
                )

    if show_block_grid and chunk_size >= 24:
        block_shapes, block_bounds = block_grid_for_region(
            x,
            y,
            chunk_size,
            region_coord,
            show_coordinates=show_coordinates,
            selected_chunk=selected_chunk,
        )
        shapes.extend(block_shapes)

    if selected_chunk is not None:
        scx, scz = selected_chunk
        if scx // 32 == rx and scz // 32 == rz:
            local_x = scx - rx * 32
            local_z = scz - rz * 32
            shapes.append(
                cv.Rect(
                    x + local_x * chunk_size,
                    y + local_z * chunk_size,
                    chunk_size,
                    chunk_size,
                    paint=ft.Paint(
                        color="#FFD54F",
                        style=ft.PaintingStyle.STROKE,
                        stroke_width=max(1.5, min(3.0, chunk_size / 3)),
                    ),
                )
            )
    return shapes, chunk_bounds, block_bounds


def marker_overlay(
    markers: Iterable[MapMarker],
    *,
    block_to_screen: BlockToScreen,
    width: float,
    height: float,
    scale: float,
    selected_id: Optional[str] = None,
) -> Tuple[List[cv.Shape], Dict[str, ScreenRect]]:
    """Draw visible waypoint markers and return their hit rectangles.

    Marker geometry is deliberately independent from the base region shapes.
    A small clamp keeps an off-screen waypoint discoverable at the edge, as in
    Xaero's world map, while the returned hit boxes remain stable per frame.
    """
    shapes: List[cv.Shape] = []
    bounds: Dict[str, ScreenRect] = {}
    radius = max(4.0, min(10.0, 4.0 + float(scale) * 0.7))
    for marker in markers:
        if not marker.enabled:
            continue
        point = _marker_screen_point(
            marker,
            block_to_screen=block_to_screen,
            width=width,
            height=height,
            radius=radius,
        )
        if point is None:
            continue
        draw_x, draw_y = point
        selected = marker.id == selected_id
        bounds[marker.id] = (
            draw_x - radius - 4,
            draw_y - radius - 4,
            radius * 2 + 8,
            radius * 2 + 8,
        )
        shapes.extend(
            _marker_pin_shapes(
                draw_x,
                draw_y,
                radius,
                marker.color,
                selected=selected,
            )
        )
        if marker.show_label and (scale >= 0.55 or selected):
            shapes.extend(
                _marker_label_shapes(
                    marker.name,
                    draw_x,
                    draw_y,
                    radius,
                    width,
                    height,
                )
            )
    return shapes, bounds


def _marker_screen_point(
    marker: MapMarker,
    *,
    block_to_screen: BlockToScreen,
    width: float,
    height: float,
    radius: float,
) -> Optional[Tuple[float, float]]:
    try:
        screen_x, screen_y = block_to_screen(marker.x, marker.z)
    except (TypeError, ValueError):
        return None
    # Skip markers that are far outside the viewport, but clamp nearby
    # ones so a search result remains visible while panning.
    if screen_x < -radius * 8 or screen_x > width + radius * 8:
        return None
    if screen_y < -radius * 8 or screen_y > height + radius * 8:
        return None
    draw_x = min(max(screen_x, radius + 2), max(radius + 2, width - radius - 2))
    draw_y = min(max(screen_y, radius + 2), max(radius + 2, height - radius - 2))
    return draw_x, draw_y


def _marker_pin_shapes(
    draw_x: float,
    draw_y: float,
    radius: float,
    color: str,
    *,
    selected: bool,
) -> List[cv.Shape]:
    shapes: List[cv.Shape] = [
        cv.Circle(
            draw_x,
            draw_y,
            radius + (2 if selected else 0),
            paint=ft.Paint(color="#FFFFFF" if selected else "#000000AA"),
        ),
        cv.Circle(
            draw_x,
            draw_y,
            radius,
            paint=ft.Paint(color=color),
        ),
        # A tiny stem gives the generic pin icon a recognizable silhouette.
        cv.Line(
            draw_x,
            draw_y + radius,
            draw_x,
            draw_y + radius + 5,
            paint=ft.Paint(color=color, stroke_width=2),
        ),
    ]
    return shapes


def _marker_label_shapes(
    name: str,
    draw_x: float,
    draw_y: float,
    radius: float,
    width: float,
    height: float,
) -> List[cv.Shape]:
    label = name[:24]
    text_width = max(34, len(label) * 7 + 10)
    label_x = min(max(draw_x + radius + 4, 4), max(4, width - text_width - 4))
    label_y = min(max(draw_y - 8, 4), max(4, height - 20))
    return [
        cv.Rect(
            label_x - 3,
            label_y - 2,
            text_width,
            18,
            paint=ft.Paint(color="#101810CC"),
        ),
        cv.Text(
            x=label_x + 2,
            y=label_y + 2,
            value=label,
            style=ft.TextStyle(size=10, color="#F6E7B0"),
        ),
    ]


def block_grid_for_region(
    region_x: float,
    region_y: float,
    chunk_size: float,
    region_coord: Coord,
    *,
    show_coordinates: bool,
    selected_chunk: Optional[Coord],
) -> Tuple[List[cv.Shape], Dict[Coord, ScreenRect]]:
    shapes: List[cv.Shape] = []
    block_bounds: Dict[Coord, ScreenRect] = {}
    block_px = chunk_size / 16.0
    if block_px < 2.0:
        return shapes, block_bounds

    rx, rz = region_coord
    for local_x, local_z in _block_grid_targets(region_coord, selected_chunk):
        bx = region_x + local_x * chunk_size
        by = region_y + local_z * chunk_size
        _append_block_grid_lines(shapes, bx, by, chunk_size, block_px)
        _append_block_coordinate(
            shapes, bx, by, region_coord, local_x, local_z, show_coordinates, block_px
        )
        if block_px >= 4:
            _record_block_bounds(block_bounds, bx, by, region_coord, local_x, local_z, block_px)
    return shapes, block_bounds


def _block_grid_targets(
    region_coord: Coord,
    selected_chunk: Optional[Coord],
) -> List[Coord]:
    if selected_chunk is None:
        return [(15, 15)]
    region_x, region_z = region_coord
    chunk_x, chunk_z = selected_chunk
    if chunk_x // 32 != region_x or chunk_z // 32 != region_z:
        return [(15, 15)]
    return [(chunk_x - region_x * 32, chunk_z - region_z * 32)]


def _append_block_grid_lines(
    shapes: List[cv.Shape],
    x: float,
    y: float,
    chunk_size: float,
    block_px: float,
) -> None:
    line_color = "#FFFFFF33" if block_px >= 4 else "#FFFFFF22"
    paint = ft.Paint(color=line_color, stroke_width=0.5)
    for index in range(1, 16):
        position = index * block_px
        shapes.extend((
            cv.Line(x + position, y, x + position, y + chunk_size, paint=paint),
            cv.Line(x, y + position, x + chunk_size, y + position, paint=paint),
        ))


def _append_block_coordinate(
    shapes: List[cv.Shape],
    x: float,
    y: float,
    region_coord: Coord,
    local_x: int,
    local_z: int,
    show_coordinates: bool,
    block_px: float,
) -> None:
    if not show_coordinates or block_px < 6:
        return
    region_x, region_z = region_coord
    chunk_x = region_x * 32 + local_x
    chunk_z = region_z * 32 + local_z
    shapes.append(
        cv.Text(
            x=x + 2,
            y=y + 2,
            value=f"{chunk_x * 16},{chunk_z * 16}",
            style=ft.TextStyle(size=10, color="#FFF59D"),
        )
    )


def _record_block_bounds(
    block_bounds: Dict[Coord, ScreenRect],
    x: float,
    y: float,
    region_coord: Coord,
    local_x: int,
    local_z: int,
    block_px: float,
) -> None:
    region_x, region_z = region_coord
    world_x = (region_x * 32 + local_x) * 16
    world_z = (region_z * 32 + local_z) * 16
    for block_z in range(16):
        for block_x in range(16):
            block_bounds[(world_x + block_x, world_z + block_z)] = (
                x + block_x * block_px,
                y + block_z * block_px,
                block_px,
                block_px,
            )


def info_overlay(
    *,
    width: float,
    height: float,
    display_mode: str,
    view_level: MapViewLevel,
    scale: float,
    is_scanning: bool,
    scan_progress: float,
    selected_region: Optional[Coord],
    selected_chunk: Optional[Coord],
    show_coordinates: bool = False,
) -> List[cv.Shape]:
    shapes: List[cv.Shape] = []
    level_title = {
        "world": "世界",
        "region": "区域",
        "chunk": "区块",
        "block": "区块内",
    }.get(view_level, "世界")
    title = f"{get_mode_title(display_mode)} · {level_title} · {scale:.1f}x"
    shapes.append(cv.Rect(10, 10, 260, 26, paint=ft.Paint(color="#00000099")))
    shapes.append(
        cv.Text(
            x=15,
            y=15,
            value=title,
            style=ft.TextStyle(size=12, color="#D7CCC8"),
        )
    )
    if is_scanning:
        shapes.append(
            cv.Rect(10, height - 34, 120, 24, paint=ft.Paint(color="#00000088"))
        )
        shapes.append(
            cv.Text(
                x=15,
                y=height - 29,
                value=f"扫描中: {int(scan_progress * 100)}%",
                style=ft.TextStyle(size=12, color="#64B5F6"),
            )
        )

    if show_coordinates and selected_region:
        if selected_chunk is not None:
            cx, cz = selected_chunk
            prefix = "区块内" if view_level == "block" else "区块"
            info = (
                f"{prefix} ({cx},{cz}) · "
                f"{format_chunk_block_range(selected_chunk)}"
            )
        else:
            info = (
                f"r.{selected_region[0]}.{selected_region[1]}.mca · "
                f"{format_region_block_range(selected_region)}"
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
