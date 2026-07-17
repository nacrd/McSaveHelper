"""Tests for the extracted map fullscreen lifecycle."""
from types import SimpleNamespace
from typing import cast

import flet as ft

from app.services.region_map_service import RegionMapService
from app.ui.views.explorer.map.fullscreen import MapFullscreenController
from app.ui.views.explorer.map.mca_map_view import McaMapView


def _controller(side_visible=True):
    service = RegionMapService()
    map_view = McaMapView(map_service=service, width=900, height=560)
    host = ft.Container(content=map_view)
    side = ft.Container(visible=side_visible)
    labels = []
    controller = MapFullscreenController(
        page=None,
        map_view=map_view,
        inline_host=host,
        side_panel=side,
        set_toggle_label=labels.append,
        refresh=lambda: None,
        zoom_in=lambda: None,
        zoom_out=lambda: None,
        reset=lambda: None,
    )
    return controller, service, map_view, host, side, labels


def test_tab_only_fullscreen_restores_map_and_visibility() -> None:
    controller, service, map_view, host, side, labels = _controller()

    controller.enter()
    assert controller.active is True
    assert side.visible is False
    assert labels[-1] == "⛶ 退出"

    controller.exit()
    assert controller.active is False
    assert side.visible is True
    assert host.content is map_view
    assert (map_view.width, map_view.height) == (900, 560)
    assert labels[-1] == "⛶ 全屏"

    controller.dispose()
    service.close()


def test_dispose_preserves_initially_hidden_side_panel() -> None:
    controller, service, _, _, side, _ = _controller(side_visible=False)

    controller.enter()
    controller.dispose()

    assert controller.active is False
    assert side.visible is False
    service.close()


def test_window_size_uses_page_and_native_window_bounds() -> None:
    page = cast(ft.Page, SimpleNamespace(
        width=640,
        height=480,
        window=SimpleNamespace(width=1280, height=720),
    ))

    assert MapFullscreenController.window_size(page) == (1280, 720)
