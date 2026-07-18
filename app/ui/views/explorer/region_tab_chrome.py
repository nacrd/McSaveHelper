"""UI composition helpers for the Explorer region map tab."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from app.ui.components.buttons import btn_danger, btn_ghost, btn_primary
from app.ui.components.cards import card
from app.ui.theme import THEME, mc_border

EventCallback = Callable[[Any], None]
SimpleCallback = Callable[[], None]

REGION_DISPLAY_HELP = (
    "按区域最高方块着色的俯视图；扫描时渐进加载，"
    "未加载前显示绿色占位。"
)
REGION_LEGEND = (
    ("#228B22", "草地", "植被"),
    ("#64A4DF", "水体", "海/河"),
    ("#EED6AF", "沙地", "沙漠"),
    ("#808080", "岩石", "石/深板岩"),
    ("#4CAF50", "占位", "未加载"),
    ("#FFD54F", "选中", "边框"),
)


@dataclass(frozen=True)
class RegionTabChrome:
    layout: ft.Row
    dimension_dropdown: ft.Dropdown
    display_mode_dropdown: ft.Dropdown
    coord_button: Any
    empty_button: Any
    fullscreen_button: Any
    help_text: ft.Text
    stats_text: ft.Text
    status_text: ft.Text
    legend_container: ft.Container
    toolbar: ft.Container
    map_host: ft.Container
    map_card: ft.Container
    left_panel: ft.Container
    side_panel: ft.Container


def build_region_legend_content() -> ft.Column:
    """Build the fixed top-view legend displayed in the side rail."""
    rows = [
        ft.Row(
            [
                ft.Container(width=18, height=18, bgcolor=color, border_radius=2),
                ft.Text(title, size=11, color=THEME.text_primary, width=58),
                ft.Text(description, size=10, color=THEME.text_muted),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        for color, title, description in REGION_LEGEND
    ]
    return ft.Column(
        [
            ft.Text(
                "🗺️ 俯视图例",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            *rows,
        ],
        spacing=5,
    )


def build_map_fallback() -> ft.Container:
    """Build the fallback shown when the MCA map control cannot initialize."""
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.WARNING, size=48, color="#FF9800"),
                ft.Text(
                    "区域地图组件不可用",
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Text(
                    "请升级 Flet 版本以启用区域地图功能",
                    size=13,
                    color=THEME.text_muted,
                ),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=50,
        bgcolor=THEME.bg_card,
        border_radius=8,
    )


def build_region_tab_chrome(
    *,
    map_content: ft.Control,
    on_dimension_changed: EventCallback,
    on_display_mode_changed: SimpleCallback,
    on_refresh: SimpleCallback,
    on_zoom_in: SimpleCallback,
    on_zoom_out: SimpleCallback,
    on_reset: SimpleCallback,
    on_toggle_coordinates: SimpleCallback,
    on_toggle_empty: SimpleCallback,
    on_toggle_fullscreen: SimpleCallback,
    on_fill_nbt: EventCallback,
    on_delete_region: EventCallback,
) -> RegionTabChrome:
    """Build the region tab controls and return stable control references."""
    dimension_dropdown = ft.Dropdown(
        options=[],
        on_select=on_dimension_changed,
        border_color=THEME.border_standard,
        text_size=13,
        width=180,
    )
    dimension_row = ft.Row(
        [
            ft.Text(
                "维度：",
                size=14,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            dimension_dropdown,
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    help_text = ft.Text(
        "滚轮缩放自动切层级 · 双击深入区块/区块内 · "
        "右键逐级返回 · 坐标随缩放变为游戏坐标",
        size=11,
        color=THEME.text_muted,
        no_wrap=True,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    display_mode_dropdown = ft.Dropdown(
        label="显示方式",
        value="topview",
        width=150,
        options=[ft.dropdown.Option("topview", "方块俯视")],
        on_select=lambda _event: on_display_mode_changed(),
        border_color=THEME.border_light,
        focused_border_color=THEME.accent,
        color=THEME.text_primary,
        bgcolor=THEME.bg_card,
    )

    coord_button = btn_ghost(
        "隐藏坐标",
        width=88,
        on_click=lambda _event: on_toggle_coordinates(),
    )
    empty_button = btn_ghost(
        "显示空格",
        width=88,
        on_click=lambda _event: on_toggle_empty(),
    )
    fullscreen_button = btn_ghost(
        "⛶ 全屏",
        width=88,
        on_click=lambda _event: on_toggle_fullscreen(),
    )
    stats_text = ft.Text(
        "等待设置当前存档...",
        size=11,
        color=THEME.text_muted,
    )
    status_text = ft.Text(
        "👆 点击方块查看详情",
        size=12,
        color=THEME.text_secondary,
    )

    view_options = ft.Row(
        [coord_button, empty_button, fullscreen_button],
        spacing=6,
    )
    toolbar = card(
        ft.Row(
            [
                dimension_row,
                display_mode_dropdown,
                btn_primary(
                    "🔄 刷新",
                    width=84,
                    on_click=lambda _event: on_refresh(),
                ),
                btn_ghost(
                    "🔍+",
                    width=52,
                    on_click=lambda _event: on_zoom_in(),
                ),
                btn_ghost(
                    "🔍−",
                    width=52,
                    on_click=lambda _event: on_zoom_out(),
                ),
                btn_ghost(
                    "🏠",
                    width=52,
                    on_click=lambda _event: on_reset(),
                ),
                view_options,
                help_text,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
        ),
        padding=8,
    )

    map_host = ft.Container(
        content=map_content,
        bgcolor=THEME.bg_secondary,
        border=mc_border(2),
        border_radius=0,
        padding=2,
        expand=True,
        alignment=ft.alignment.Alignment(0, 0),
    )
    map_card = card(map_host, padding=4)
    map_card.expand = True
    legend_container = ft.Container(content=build_region_legend_content())

    selection_card = card(
        ft.Column(
            [
                ft.Text(
                    "👆 选中",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                status_text,
            ],
            spacing=4,
        ),
        padding=8,
    )
    stats_card = card(
        ft.Column(
            [
                ft.Text(
                    "📊 概况",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                stats_text,
            ],
            spacing=4,
        ),
        padding=8,
    )
    action_card = card(
        ft.Column(
            [
                ft.Text(
                    "🛠️ 操作",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Row(
                    [
                        btn_ghost("填入 NBT", width=100, on_click=on_fill_nbt),
                        btn_danger(
                            "删除区域",
                            width=100,
                            on_click=on_delete_region,
                        ),
                    ],
                    spacing=6,
                ),
            ],
            spacing=6,
        ),
        padding=8,
    )

    left_panel = ft.Container(
        content=ft.Column([toolbar, map_card], spacing=6, expand=True),
        expand=True,
    )
    side_panel = ft.Container(
        content=ft.Column(
            [
                selection_card,
                stats_card,
                card(legend_container, padding=8),
                action_card,
            ],
            spacing=6,
        ),
        width=280,
        expand=False,
    )
    layout = ft.Row(
        [left_panel, side_panel],
        spacing=10,
        expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return RegionTabChrome(
        layout=layout,
        dimension_dropdown=dimension_dropdown,
        display_mode_dropdown=display_mode_dropdown,
        coord_button=coord_button,
        empty_button=empty_button,
        fullscreen_button=fullscreen_button,
        help_text=help_text,
        stats_text=stats_text,
        status_text=status_text,
        legend_container=legend_container,
        toolbar=toolbar,
        map_host=map_host,
        map_card=map_card,
        left_panel=left_panel,
        side_panel=side_panel,
    )
