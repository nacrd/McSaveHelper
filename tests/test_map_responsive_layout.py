"""Responsive sizing contracts for the inline MCA map."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, cast

import flet as ft

from app.services.execution_runtime import ExecutionRuntime
from app.services.region_map import RegionMapService
from app.ui.views.explorer.map.mca_map_view import McaMapView
from app.ui.views.explorer.region_tab_chrome import build_region_tab_chrome


def _build_chrome(map_view: McaMapView):
    def noop(*args: object) -> None:
        del args

    return build_region_tab_chrome(
        map_content=map_view,
        on_dimension_changed=noop,
        on_display_mode_changed=noop,
        on_refresh=noop,
        on_zoom_in=noop,
        on_zoom_out=noop,
        on_reset=noop,
        on_toggle_coordinates=noop,
        on_toggle_empty=noop,
        on_toggle_fullscreen=noop,
        on_fill_nbt=noop,
        on_delete_region=noop,
    )


def test_inline_map_stacks_force_the_map_to_fill_available_space() -> None:
    service = RegionMapService(ExecutionRuntime())
    view = McaMapView(map_service=service, width=900, height=560)

    inner_stack = cast(ft.Stack, view.content)
    chrome = _build_chrome(view)
    outer_stack = cast(ft.Stack, chrome.map_host.content)

    assert inner_stack.fit is ft.StackFit.EXPAND
    assert outer_stack.fit is ft.StackFit.EXPAND
    assert view._canvas.width is None
    assert view._canvas.height is None
    assert view._gesture.width is None
    assert view._gesture.height is None
    service.close()


def test_canvas_measurement_updates_viewport_without_locking_child_layers() -> None:
    service = RegionMapService(ExecutionRuntime())
    view = McaMapView(map_service=service, width=900, height=560)
    view._viewport.offset_x = 37.0
    view._viewport.offset_y = -19.0
    rebuilds: list[None] = []
    view._request_rebuild = cast(Any, lambda: rebuilds.append(None))

    event = SimpleNamespace(width=1180.9, height=704.2)
    view._on_canvas_resize(event)

    assert (view.width, view.height) == (1180, 704)
    assert (view._viewport.offset_x, view._viewport.offset_y) == (37.0, -19.0)
    assert view._canvas.width is None
    assert view._canvas.height is None
    assert view._gesture.width is None
    assert view._gesture.height is None
    assert rebuilds == [None]

    view._on_canvas_resize(event)
    assert rebuilds == [None]
    service.close()


def test_expanding_map_host_propagates_window_size_to_map_view() -> None:
    service = RegionMapService(ExecutionRuntime())
    view = McaMapView(map_service=service, width=900, height=560)
    chrome = _build_chrome(view)
    rebuilds: list[None] = []
    view._request_rebuild = cast(Any, lambda: rebuilds.append(None))

    callback = chrome.map_host.on_size_change
    assert callback is not None
    cast(Callable[[Any], None], callback)(
        SimpleNamespace(width=1260.8, height=732.4)
    )

    assert (view.width, view.height) == (1260, 732)
    assert rebuilds == [None]
    service.close()
