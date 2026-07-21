"""Tests for WindowManager's explicit responsive shell host."""
from types import SimpleNamespace
from typing import cast

import flet as ft

from app.core.window_manager import (
    ResponsiveShellHost,
    WindowManager,
    WindowManagerDependencies,
)


class FakeSidebar:
    def __init__(self) -> None:
        self.collapsed = None
        self.width = None

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed

    def set_width(self, width: int) -> None:
        self.width = width


def test_responsive_layout_uses_attached_shell_host() -> None:
    compact_modes = []
    page = cast(
        ft.Page,
        SimpleNamespace(window=SimpleNamespace(width=700)),
    )
    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=compact_modes.append,
        get_sidebar_mode=lambda: "auto",
        stop_gui_optimizer=lambda: None,
        dispose_views=lambda: None,
    ))
    sidebar = FakeSidebar()
    main_row = ft.Row(spacing=12)
    shell = ft.Container()
    scrollable = ft.Container()
    content = ft.Container()
    manager.attach_responsive_host(ResponsiveShellHost(
        sidebar=sidebar,
        main_row=main_row,
        shell=shell,
        scrollable_content=scrollable,
        content=content,
    ))

    manager.apply_responsive_layout(700, 600)

    assert sidebar.collapsed is True
    assert main_row.spacing == 0
    assert shell.padding == 0
    assert scrollable.padding == 0
    assert content.padding == 10
    assert compact_modes[-1].density == "narrow"

    page.window.width = 1400
    manager.apply_responsive_layout(1400, 900)
    assert sidebar.collapsed is False
    assert sidebar.width == 280
    assert content.padding == 28
    assert compact_modes[-1].density == "roomy"


def test_responsive_layout_preserves_collapsed_user_preference() -> None:
    page = cast(
        ft.Page,
        SimpleNamespace(window=SimpleNamespace(width=1200)),
    )
    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=lambda layout: None,
        get_sidebar_mode=lambda: "collapsed",
        stop_gui_optimizer=lambda: None,
        dispose_views=lambda: None,
    ))
    sidebar = FakeSidebar()
    manager.attach_responsive_host(ResponsiveShellHost(
        sidebar=sidebar,
        main_row=ft.Row(),
        shell=ft.Container(),
        scrollable_content=ft.Container(),
        content=ft.Container(),
    ))

    manager.apply_responsive_layout(1200, 820)

    assert sidebar.collapsed is True
    assert sidebar.width == 248


def test_refresh_responsive_layout_reads_current_window_size() -> None:
    layouts = []
    page = cast(
        ft.Page,
        SimpleNamespace(window=SimpleNamespace(width=900, height=820)),
    )
    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=layouts.append,
        get_sidebar_mode=lambda: "auto",
        stop_gui_optimizer=lambda: None,
        dispose_views=lambda: None,
    ))

    manager._capture_viewport_size(
        SimpleNamespace(width=900, height=820)
    )
    manager.refresh_responsive_layout()

    assert layouts[-1].density == "compact"


def test_resize_event_dimensions_override_stale_window_dimensions() -> None:
    page = cast(
        ft.Page,
        SimpleNamespace(window=SimpleNamespace(width=1100, height=820)),
    )
    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=lambda layout: None,
        get_sidebar_mode=lambda: "auto",
        stop_gui_optimizer=lambda: None,
        dispose_views=lambda: None,
    ))

    manager._capture_viewport_size(
        SimpleNamespace(width=800, height=600)
    )

    assert manager._viewport_size == (800.0, 600.0)


def test_refresh_prefers_live_page_viewport_over_desktop_window() -> None:
    layouts = []
    page = cast(
        ft.Page,
        SimpleNamespace(
            width=800,
            height=600,
            window=SimpleNamespace(width=1100, height=820),
        ),
    )
    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=layouts.append,
        get_sidebar_mode=lambda: "auto",
        stop_gui_optimizer=lambda: None,
        dispose_views=lambda: None,
    ))

    manager.refresh_responsive_layout()

    assert layouts[-1].density == "narrow"


def test_shutdown_does_not_schedule_forced_process_exit() -> None:
    from pathlib import Path

    source = Path("app/core/window_manager.py").read_text(encoding="utf-8")
    assert "os._exit" not in source
    assert "_schedule_force_exit" not in source
