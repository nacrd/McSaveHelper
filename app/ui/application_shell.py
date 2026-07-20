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
from app.ui.theme import THEME, mc_border, mc_shadow


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
    top_actions: ft.Row
    progress_control: ft.Control
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
        ("map_export", "sidebar.map_export", "地图导出", IconSet.EXPORT),
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
        padding=20,
        bgcolor=THEME.bg_card,
        border=mc_border(3),
        border_radius=8,
        expand=True,
    )
    sidebar = _build_shell_sidebar(dependencies, tab_defs)
    top_bar = _build_top_bar(dependencies.translate, dependencies.top_actions)
    scrollable_content = ft.Container(
        content=content,
        padding=16,
        expand=True,
    )
    content_area = ft.Column(
        [top_bar, scrollable_content],
        spacing=0,
        expand=True,
    )
    floating_log_panel, log_button = _build_shell_log_controls(dependencies)
    right_panel = ft.Stack(
        [content_area, floating_log_panel, log_button],
        expand=True,
    )
    main_row = ft.Row(
        [sidebar, right_panel],
        spacing=14,
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


def _build_top_bar(translate: Translate, top_actions: ft.Row) -> ft.Container:
    identity = _build_top_bar_identity(translate)
    header = ft.Container(
        content=ft.Row(
            [identity, top_actions],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding(left=20, right=20, top=14, bottom=14),
        bgcolor=THEME.mc_wood,
    )
    grass_strip = ft.Container(
        height=6,
        bgcolor=THEME.mc_grass,
        border_radius=ft.BorderRadius(
            top_left=8,
            top_right=8,
            bottom_left=0,
            bottom_right=0,
        ),
    )
    return ft.Container(
        content=ft.Column([grass_strip, header], spacing=0),
        bgcolor=THEME.mc_wood,
        border=mc_border(3),
        border_radius=8,
    )


def _build_top_bar_identity(translate: Translate) -> ft.Row:
    return ft.Row(
        [
            ft.Container(
                content=ft.Icon(
                    IconSet.PICKAXE,
                    size=24,
                    color=THEME.mc_gold,
                ),
                width=48,
                height=48,
                alignment=ft.alignment.Alignment(0, 0),
                bgcolor=THEME.bg_secondary,
                border=mc_border(2),
                border_radius=8,
            ),
            ft.Column(
                [
                    ft.Text(
                        "MCSaveHelper",
                        size=20,
                        weight=ft.FontWeight.BOLD,
                        color=THEME.text_primary,
                        font_family="monospace",
                    ),
                    ft.Text(
                        translate("app.subtitle", "存档管理工具"),
                        size=11,
                        color=THEME.mc_grass,
                        font_family="monospace",
                    ),
                ],
                spacing=3,
            ),
        ],
        spacing=14,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _build_content_shell(main_row: ft.Row) -> ft.Container:
    return ft.Container(
        content=main_row,
        padding=14,
        margin=ft.Margin(left=14, right=14, top=0, bottom=14),
        bgcolor=THEME.bg_primary,
        border=ft.Border(
            left=ft.BorderSide(4, THEME.border_light),
            top=ft.BorderSide(0, ft.Colors.TRANSPARENT),
            right=ft.BorderSide(4, THEME.border_dark),
            bottom=ft.BorderSide(4, THEME.border_dark),
        ),
        border_radius=10,
        shadow=mc_shadow(6),
        expand=True,
    )


def _build_bottom_bar(progress_control: ft.Control) -> ft.Container:
    return ft.Container(
        content=ft.Container(
            content=progress_control,
            padding=ft.Padding(left=20, right=20, top=10, bottom=10),
            bgcolor=THEME.mc_wood,
            border_radius=6,
        ),
        bgcolor=THEME.mc_wood,
        border=ft.Border(
            left=ft.BorderSide(3, THEME.border_light),
            top=ft.BorderSide(0, ft.Colors.TRANSPARENT),
            right=ft.BorderSide(3, THEME.border_dark),
            bottom=ft.BorderSide(3, THEME.border_dark),
        ),
        border_radius=8,
        margin=ft.Margin(left=14, right=14, top=0, bottom=14),
    )
