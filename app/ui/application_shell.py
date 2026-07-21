"""Application shell construction kept separate from the composition root."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence

import flet as ft

from app.ui.components.floating_log_panel import (
    FloatingLogButton,
    FloatingLogPanel,
)
from app.ui.icons import IconSet
from app.ui.sidebar import Sidebar
from app.ui.theme import THEME


Translate = Callable[..., str]


@dataclass(frozen=True)
class ApplicationShellDependencies:
    """Callbacks and controls required to assemble the main application shell."""

    page: ft.Page
    translate: Translate
    on_tab_select: Callable[[str], None]
    on_tabs_reorder: Callable[[list], None]
    on_import_save: Callable[[], None]
    on_recent_save_select: Callable[[str], None]
    recent_saves: Sequence[Dict[str, Any]]
    show_log_panel: bool
    progress_control: ft.Container
    title_bar: ft.Control


@dataclass(frozen=True)
class ApplicationShell:
    """Controls exposed to managers after the shell has been assembled."""

    tab_defs: List[Dict[str, Any]]
    content: ft.Container
    sidebar: Sidebar
    scrollable_content: ft.Container
    floating_log_panel: FloatingLogPanel
    log_button: FloatingLogButton
    main_row: ft.Row
    shell: ft.Container
    frame: ft.Column


def build_tab_definitions(translate: Translate) -> List[Dict[str, Any]]:
    """Build the translated sidebar catalog in one deterministic place."""
    definitions = (
        ("explorer", "sidebar.explorer", "存档浏览器", IconSet.MAP),
        ("migrator", "sidebar.migrator", "存档转换", IconSet.PACKAGE),
        ("save_repair", "sidebar.save_repair", "存档修复", IconSet.BUILD),
        ("backup_center", "sidebar.backup_center", "备份与恢复", IconSet.HISTORY),
        ("compare", "sidebar.compare", "存档对比", IconSet.BALANCE),
        ("mappings", "sidebar.mappings", "映射管理", IconSet.LINK),
        (
            "server_properties",
            "sidebar.server_properties",
            "服务器配置",
            IconSet.CLIPBOARD,
        ),
        ("settings", "sidebar.settings", "设置", IconSet.SETTINGS),
    )
    return [
        {
            "id": view_id,
            "label": translate(translation_key, default),
            "icon": icon,
        }
        for view_id, translation_key, default, icon in definitions
    ]


def build_application_shell(
    dependencies: ApplicationShellDependencies,
) -> ApplicationShell:
    """Assemble the visual shell without coordinating application services."""
    tab_defs = build_tab_definitions(dependencies.translate)
    content = ft.Container(
        padding=24,
        bgcolor=THEME.bg_primary,
        expand=True,
    )
    sidebar = _build_shell_sidebar(dependencies, tab_defs)
    scrollable_content = ft.Container(
        content=content,
        padding=0,
        expand=True,
    )
    floating_log_panel, log_button = _build_shell_log_controls(dependencies)
    right_panel = ft.Stack(
        [scrollable_content, floating_log_panel, log_button],
        expand=True,
    )
    main_row = ft.Row(
        [sidebar, right_panel],
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.START,
        expand=True,
    )
    shell = _build_content_shell(main_row)
    bottom_bar = _build_bottom_bar(dependencies.progress_control)
    frame = ft.Column(
        [dependencies.title_bar, shell, bottom_bar],
        spacing=0,
        expand=True,
    )
    return ApplicationShell(
        tab_defs=tab_defs,
        content=content,
        sidebar=sidebar,
        scrollable_content=scrollable_content,
        floating_log_panel=floating_log_panel,
        log_button=log_button,
        main_row=main_row,
        shell=shell,
        frame=frame,
    )


def _build_shell_sidebar(
    dependencies: ApplicationShellDependencies,
    tab_defs: list[dict],
) -> Sidebar:
    return Sidebar(
        tabs=tab_defs,
        on_tab_select=dependencies.on_tab_select,
        on_tabs_reorder=dependencies.on_tabs_reorder,
        on_import_save=dependencies.on_import_save,
        on_set_current_save=dependencies.on_import_save,
        on_recent_save_select=dependencies.on_recent_save_select,
        recent_saves=list(dependencies.recent_saves),
        default_tab="explorer",
        translate=dependencies.translate,
    )


def _build_shell_log_controls(
    dependencies: ApplicationShellDependencies,
) -> tuple[FloatingLogPanel, FloatingLogButton]:
    floating_log_panel = FloatingLogPanel(
        page=dependencies.page,
        title=dependencies.translate("log_panel.title", "日志"),
    )
    log_button = FloatingLogButton(
        floating_panel=floating_log_panel,
        page=dependencies.page,
    )
    log_button.set_visible(dependencies.show_log_panel)
    floating_log_panel.set_visible(False)
    return floating_log_panel, log_button


def _build_content_shell(main_row: ft.Row) -> ft.Container:
    return ft.Container(
        content=main_row,
        bgcolor=THEME.bg_primary,
        expand=True,
    )


def _build_bottom_bar(progress_control: ft.Container) -> ft.Container:
    """Style the progress host without adding an always-visible wrapper."""
    progress_control.padding = ft.Padding(left=20, right=20, top=8, bottom=8)
    progress_control.bgcolor = THEME.bg_secondary
    progress_control.border = ft.Border(
        top=ft.BorderSide(1, THEME.border_subtle),
    )
    return progress_control
