"""Tests for the extracted map fullscreen lifecycle."""
from types import SimpleNamespace
from typing import cast

import flet as ft
import pytest

from app.services.execution_runtime import ExecutionRuntime
from app.services.region_map import RegionMapService
from app.ui.views.explorer.map.fullscreen import MapFullscreenController
from app.ui.views.explorer.map.mca_map_view import McaMapView


class _DelayedCall:
    def __init__(self, callback):
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback()


class _DelayedScheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, _delay, callback):
        call = _DelayedCall(callback)
        self.calls.append(call)
        return call


class _FailingScheduler:
    def __call__(self, _delay, _callback):
        raise RuntimeError("scheduler failed")


def _controller(side_visible=True):
    service = RegionMapService(ExecutionRuntime())
    map_view = McaMapView(map_service=service, width=900, height=560)
    host = ft.Container(content=map_view)
    side = ft.Container(visible=side_visible)
    states = []
    controller = MapFullscreenController(
        page=None,
        map_view=map_view,
        inline_host=host,
        side_panel=side,
        set_toggle_state=states.append,
        refresh=lambda: None,
        zoom_in=lambda: None,
        zoom_out=lambda: None,
        reset=lambda: None,
    )
    return controller, service, map_view, host, side, states


def test_tab_only_fullscreen_restores_map_and_visibility() -> None:
    controller, service, map_view, host, side, states = _controller()

    controller.enter()
    assert controller.active is True
    assert side.visible is False
    assert states[-1] is True

    controller.exit()
    assert controller.active is False
    assert side.visible is True
    assert host.content is map_view
    assert (map_view.width, map_view.height) == (900, 560)
    assert states[-1] is False

    controller.dispose()
    assert host.content is map_view
    service.close()


def test_fullscreen_restore_is_idempotent_for_wrapped_inline_content() -> None:
    service = RegionMapService(ExecutionRuntime())
    map_view = McaMapView(map_service=service)
    original = ft.Stack([map_view])
    host = ft.Container(content=original)
    side = ft.Container()
    states = []
    controller = MapFullscreenController(
        page=None,
        map_view=map_view,
        inline_host=host,
        side_panel=side,
        set_toggle_state=states.append,
        refresh=lambda: None,
        zoom_in=lambda: None,
        zoom_out=lambda: None,
        reset=lambda: None,
    )

    controller.enter()
    controller.exit()
    controller.dispose()

    assert host.content is original
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


def test_fullscreen_dispose_invalidates_pending_restore_callback() -> None:
    service = RegionMapService(ExecutionRuntime())
    map_view = McaMapView(map_service=service)
    host = ft.Container(content=map_view)
    side = ft.Container()
    page = cast(
        ft.Page,
        SimpleNamespace(
            width=1280,
            height=720,
            window=SimpleNamespace(width=1280, height=720),
            overlay=[],
            update=lambda: None,
        ),
    )
    scheduler = _DelayedScheduler()
    controller = MapFullscreenController(
        page=page,
        map_view=map_view,
        inline_host=host,
        side_panel=side,
        set_toggle_state=lambda _active: None,
        refresh=lambda: None,
        zoom_in=lambda: None,
        zoom_out=lambda: None,
        reset=lambda: None,
        schedule_delayed=scheduler,
    )

    controller.enter()
    controller.exit()
    restore = scheduler.calls[-1]
    controller.dispose()
    restore.fire()

    assert controller.active is False
    assert host.content is map_view
    assert page.overlay == []
    service.close()


def test_fullscreen_recovers_when_transition_scheduler_raises() -> None:
    service = RegionMapService(ExecutionRuntime())
    map_view = McaMapView(map_service=service)
    host = ft.Container(content=map_view)
    side = ft.Container()
    page = cast(
        ft.Page,
        SimpleNamespace(
            width=1280,
            height=720,
            window=SimpleNamespace(width=1280, height=720),
            overlay=[],
            update=lambda: None,
        ),
    )
    controller = MapFullscreenController(
        page=page,
        map_view=map_view,
        inline_host=host,
        side_panel=side,
        set_toggle_state=lambda _active: None,
        refresh=lambda: None,
        zoom_in=lambda: None,
        zoom_out=lambda: None,
        reset=lambda: None,
        schedule_delayed=_FailingScheduler(),
    )

    with pytest.raises(RuntimeError, match="scheduler failed"):
        controller.enter()

    assert controller.active is False
    assert host.content is map_view
    assert page.overlay == []
    service.close()
