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
        apply_compact_layout=compact_modes.append,
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
    assert main_row.spacing == 6
    assert shell.padding == 6
    assert scrollable.padding == 6
    assert content.padding == 8
    assert compact_modes == [True]

    page.window.width = 1400
    manager.apply_responsive_layout(1400, 900)
    assert sidebar.collapsed is False
    assert sidebar.width == 230
    assert compact_modes[-1] is False


def test_shutdown_does_not_schedule_forced_process_exit() -> None:
    from pathlib import Path

    source = Path("app/core/window_manager.py").read_text(encoding="utf-8")
    assert "os._exit" not in source
    assert "_schedule_force_exit" not in source
