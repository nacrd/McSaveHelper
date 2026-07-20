"""Explorer 地图页的 Flet 外壳构建器。

布局采用 Xaero 风格的全幅地图、边缘工具列和半透明状态条。业务状态仍由
controller/service 管理，这里只创建控件并返回稳定引用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

import flet as ft

from app.ui.components.buttons import btn_danger, btn_ghost
from app.ui.components.cards import card
from app.ui.theme import THEME, mc_border

EventCallback = Callable[[Any], None]
SimpleCallback = Callable[[], None]
Translate = Callable[[str, str], str]

REGION_DISPLAY_HELP = (
    "拖拽平移，滚轮缩放；双击深入区块，右键返回上一级。"
)
REGION_LEGEND = (
    ("#228B22", "草地", "植被"),
    ("#64A4DF", "水体", "海/河"),
    ("#EED6AF", "沙地", "沙漠"),
    ("#808080", "岩石", "石/深板岩"),
    ("#4CAF50", "占位", "未加载"),
    ("#FFD54F", "选中", "边框/标记"),
)
REGION_LEGEND_KEYS = (
    ("map.legend_grass", "map.legend_vegetation"),
    ("map.legend_water", "map.legend_sea_river"),
    ("map.legend_sand", "map.legend_desert"),
    ("map.legend_rock", "map.legend_stone"),
    ("map.legend_placeholder", "map.legend_unloaded"),
    ("map.legend_selected", "map.legend_border_marker"),
)


@dataclass(frozen=True)
class RegionTabChrome:
    layout: ft.Row
    dimension_dropdown: ft.Dropdown
    display_mode_dropdown: ft.Dropdown
    search_field: ft.TextField
    search_button: ft.IconButton
    coord_button: ft.IconButton
    empty_button: ft.IconButton
    marker_button: ft.IconButton
    fullscreen_button: ft.IconButton
    add_marker_button: ft.IconButton
    delete_marker_button: ft.IconButton
    marker_list: ft.ListView
    marker_count_text: ft.Text
    help_text: ft.Text
    stats_text: ft.Text
    status_text: ft.Text
    legend_container: ft.Container
    toolbar: ft.Container
    map_host: ft.Container
    map_card: ft.Container
    left_panel: ft.Container
    side_panel: ft.Container


def _translator(translate: Optional[Translate]) -> Translate:
    return translate or (lambda _key, fallback: fallback)


def _icon_button(
    icon: ft.IconData,
    tooltip: str,
    callback: SimpleCallback,
    *,
    selected: bool = False,
) -> ft.IconButton:
    return ft.IconButton(
        icon=icon,
        selected=selected,
        icon_color=THEME.text_primary,
        selected_icon_color=THEME.mc_gold,
        bgcolor="#101810DD",
        hover_color=THEME.bg_card_hover,
        tooltip=tooltip,
        width=40,
        height=40,
        on_click=lambda _event: callback(),
    )


def _build_dimension_style_dropdowns(
    t: Translate,
    on_dimension_changed: EventCallback,
    on_display_mode_changed: SimpleCallback,
) -> tuple[ft.Dropdown, ft.Dropdown]:
    """Top-bar dimension and map-style selectors."""
    dimension_dropdown = ft.Dropdown(
        label=t("map.dimension", "维度"),
        options=[],
        on_select=on_dimension_changed,
        border_color=THEME.border_standard,
        focused_border_color=THEME.mc_diamond,
        bgcolor="#101810EE",
        color=THEME.text_primary,
        text_size=12,
        width=190,
        height=48,
    )
    display_mode_dropdown = ft.Dropdown(
        label=t("map.style", "地图样式"),
        value="topview",
        width=150,
        height=48,
        options=[
            ft.dropdown.Option("topview", t("map.style_topview", "地表")),
            ft.dropdown.Option("activity", t("map.style_region", "区域")),
            ft.dropdown.Option("biome", t("map.style_biome", "群系")),
            ft.dropdown.Option("structure", t("map.style_structure", "结构")),
        ],
        on_select=lambda _event: on_display_mode_changed(),
        border_color=THEME.border_standard,
        focused_border_color=THEME.mc_diamond,
        color=THEME.text_primary,
        bgcolor="#101810EE",
        text_size=12,
    )
    return dimension_dropdown, display_mode_dropdown


def _build_search_controls(
    t: Translate,
    search_callback: EventCallback,
) -> tuple[ft.TextField, ft.IconButton]:
    """Map search field and submit button."""
    search_field = ft.TextField(
        hint_text=t(
            "map.search_hint",
            "坐标 x,z / x y z / r.x.z / c.x.z / 标记名",
        ),
        width=300,
        height=42,
        text_size=12,
        color=THEME.text_primary,
        bgcolor="#101810EE",
        border_color=THEME.border_standard,
        focused_border_color=THEME.mc_diamond,
        content_padding=ft.Padding(left=12, right=8, top=8, bottom=8),
        on_submit=search_callback,
    )
    search_button = ft.IconButton(
        icon=ft.Icons.SEARCH,
        icon_color=THEME.text_primary,
        bgcolor="#101810EE",
        hover_color=THEME.bg_card_hover,
        tooltip=t("map.search", "搜索地图"),
        width=40,
        height=40,
        on_click=search_callback,
    )
    return search_field, search_button


def _build_map_toggle_buttons(
    t: Translate,
    on_toggle_coordinates: SimpleCallback,
    on_toggle_empty: SimpleCallback,
    marker_callback: SimpleCallback,
    on_toggle_fullscreen: SimpleCallback,
) -> tuple[ft.IconButton, ft.IconButton, ft.IconButton, ft.IconButton]:
    """Coordinate/empty/marker/fullscreen toggle buttons."""
    coord_button = _icon_button(
        ft.Icons.LABEL_OUTLINE,
        t("map.show_coordinates", "显示坐标"),
        on_toggle_coordinates,
        selected=False,
    )
    empty_button = _icon_button(
        ft.Icons.GRID_ON,
        t("map.show_empty", "显示空区域"),
        on_toggle_empty,
    )
    marker_button = _icon_button(
        ft.Icons.LOCATION_ON,
        t("map.hide_markers", "隐藏标记"),
        marker_callback,
        selected=True,
    )
    fullscreen_button = _icon_button(
        ft.Icons.FULLSCREEN,
        t("map.fullscreen", "全屏地图"),
        on_toggle_fullscreen,
    )
    return coord_button, empty_button, marker_button, fullscreen_button


def _build_floating_toolbars(
    t: Translate,
    *,
    dimension_dropdown: ft.Dropdown,
    display_mode_dropdown: ft.Dropdown,
    search_field: ft.TextField,
    search_button: ft.IconButton,
    on_zoom_in: SimpleCallback,
    on_zoom_out: SimpleCallback,
    on_reset: SimpleCallback,
    on_refresh: SimpleCallback,
    coord_button: ft.IconButton,
    empty_button: ft.IconButton,
    marker_button: ft.IconButton,
    fullscreen_button: ft.IconButton,
) -> tuple[ft.Container, ft.Container, ft.Container]:
    """Top/left/right floating toolbars over the map."""
    top_bar = _build_top_toolbar(
        dimension_dropdown=dimension_dropdown,
        display_mode_dropdown=display_mode_dropdown,
        search_field=search_field,
        search_button=search_button,
    )
    left_toolbar = _build_left_zoom_toolbar(
        t,
        on_zoom_in=on_zoom_in,
        on_zoom_out=on_zoom_out,
        on_reset=on_reset,
    )
    right_toolbar = _build_right_map_toolbar(
        t,
        on_refresh=on_refresh,
        coord_button=coord_button,
        empty_button=empty_button,
        marker_button=marker_button,
        fullscreen_button=fullscreen_button,
    )
    return top_bar, left_toolbar, right_toolbar


def _build_top_toolbar(
    *,
    dimension_dropdown: ft.Dropdown,
    display_mode_dropdown: ft.Dropdown,
    search_field: ft.TextField,
    search_button: ft.IconButton,
) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.MAP_OUTLINED, size=20, color=THEME.mc_gold),
                dimension_dropdown,
                display_mode_dropdown,
                ft.Container(expand=True),
                search_field,
                search_button,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        left=12,
        top=12,
        right=12,
        height=56,
        padding=ft.Padding(left=10, right=8, top=4, bottom=4),
        bgcolor="#0B120BE8",
        border=mc_border(1),
        border_radius=6,
    )


def _build_left_zoom_toolbar(
    t: Translate,
    *,
    on_zoom_in: SimpleCallback,
    on_zoom_out: SimpleCallback,
    on_reset: SimpleCallback,
) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                _icon_button(
                    ft.Icons.ZOOM_IN,
                    t("map.zoom_in", "放大"),
                    on_zoom_in,
                ),
                _icon_button(
                    ft.Icons.ZOOM_OUT,
                    t("map.zoom_out", "缩小"),
                    on_zoom_out,
                ),
                _icon_button(
                    ft.Icons.MY_LOCATION,
                    t("map.fit_world", "显示完整世界"),
                    on_reset,
                ),
            ],
            spacing=4,
            tight=True,
        ),
        left=12,
        top=82,
        padding=4,
        bgcolor="#0B120BCC",
        border_radius=6,
    )


def _build_right_map_toolbar(
    t: Translate,
    *,
    on_refresh: SimpleCallback,
    coord_button: ft.IconButton,
    empty_button: ft.IconButton,
    marker_button: ft.IconButton,
    fullscreen_button: ft.IconButton,
) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                _icon_button(
                    ft.Icons.REFRESH,
                    t("map.refresh", "刷新地图"),
                    on_refresh,
                ),
                coord_button,
                empty_button,
                marker_button,
                fullscreen_button,
            ],
            spacing=4,
            tight=True,
        ),
        right=12,
        top=82,
        padding=4,
        bgcolor="#0B120BCC",
        border_radius=6,
    )


def _build_map_help_bar(t: Translate) -> tuple[ft.Text, ft.Container]:
    help_text = ft.Text(
        t("map.help", REGION_DISPLAY_HELP),
        size=11,
        color="#D0D8C8",
        no_wrap=True,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    bottom_bar = ft.Container(
        content=help_text,
        left=12,
        right=12,
        bottom=12,
        height=30,
        padding=ft.Padding(left=10, right=10, top=6, bottom=5),
        bgcolor="#0B120BCC",
        border_radius=4,
    )
    return help_text, bottom_bar


def _build_map_host_stack(
    map_content: ft.Control,
    top_bar: ft.Container,
    left_toolbar: ft.Container,
    right_toolbar: ft.Container,
    bottom_bar: ft.Container,
    sync_map_size: Callable[[Any], None],
) -> tuple[ft.Container, ft.Container]:
    map_host = ft.Container(
        content=ft.Stack(
            [map_content, top_bar, left_toolbar, right_toolbar, bottom_bar],
            expand=True,
            fit=ft.StackFit.EXPAND,
        ),
        bgcolor="#0B120B",
        border=mc_border(2),
        border_radius=0,
        padding=0,
        expand=True,
        alignment=ft.Alignment(0, 0),
        on_size_change=sync_map_size,
    )
    # Compatibility alias consumed by fullscreen/layout code.
    return map_host, map_host


def build_region_legend_content(
    translate: Optional[Translate] = None,
) -> ft.Column:
    """构建固定地表图例。"""
    t = _translator(translate)
    rows = []
    for (color, title, description), (title_key, description_key) in zip(
        REGION_LEGEND,
        REGION_LEGEND_KEYS,
    ):
        rows.append(ft.Row(
            [
                ft.Container(width=16, height=16, bgcolor=color, border_radius=2),
                ft.Text(
                    t(title_key, title),
                    size=11,
                    color=THEME.text_primary,
                    width=54,
                ),
                ft.Text(
                    t(description_key, description),
                    size=10,
                    color=THEME.text_muted,
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ))
    return ft.Column(
        [
            ft.Text(
                t("map.legend", "地图图例"),
                size=12,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            *rows,
        ],
        spacing=5,
    )


def build_map_fallback(translate: Optional[Translate] = None) -> ft.Container:
    """地图 Canvas 无法初始化时显示的降级界面。"""
    t = _translator(translate)
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.WARNING, size=48, color=THEME.warning),
                ft.Text(
                    t("map.unavailable", "区域地图组件不可用"),
                    size=16,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Text(
                    t("map.upgrade_flet", "请升级 Flet 版本以启用区域地图功能"),
                    size=13,
                    color=THEME.text_muted,
                ),
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=50,
        bgcolor=THEME.bg_card,
        border_radius=6,
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
    on_search: Optional[EventCallback] = None,
    on_toggle_markers: Optional[SimpleCallback] = None,
    on_add_marker: Optional[EventCallback] = None,
    on_delete_marker: Optional[EventCallback] = None,
    translate: Optional[Translate] = None,
) -> RegionTabChrome:
    """创建地图页面，并返回 controller 需要更新的控件引用。"""
    t = _translator(translate)
    search_callback = on_search or (lambda _event: None)
    marker_callback = on_toggle_markers or (lambda: None)
    add_marker_callback = on_add_marker or (lambda _event: None)
    delete_marker_callback = on_delete_marker or (lambda _event: None)

    def sync_map_size(event: Any) -> None:
        """Propagate the expanding host's measured size to the map camera."""
        resize = getattr(map_content, "resize_map", None)
        if not callable(resize):
            return
        try:
            width = int(getattr(event, "width", 0) or 0)
            height = int(getattr(event, "height", 0) or 0)
        except (TypeError, ValueError):
            return
        if width >= 80 and height >= 80:
            resize(width, height)

    dimension_dropdown, display_mode_dropdown = _build_dimension_style_dropdowns(
        t,
        on_dimension_changed,
        on_display_mode_changed,
    )
    search_field, search_button = _build_search_controls(t, search_callback)
    (
        coord_button,
        empty_button,
        marker_button,
        fullscreen_button,
    ) = _build_map_toggle_buttons(
        t,
        on_toggle_coordinates,
        on_toggle_empty,
        marker_callback,
        on_toggle_fullscreen,
    )

    top_bar, left_toolbar, right_toolbar = _build_floating_toolbars(
        t,
        dimension_dropdown=dimension_dropdown,
        display_mode_dropdown=display_mode_dropdown,
        search_field=search_field,
        search_button=search_button,
        on_zoom_in=on_zoom_in,
        on_zoom_out=on_zoom_out,
        on_reset=on_reset,
        on_refresh=on_refresh,
        coord_button=coord_button,
        empty_button=empty_button,
        marker_button=marker_button,
        fullscreen_button=fullscreen_button,
    )
    help_text, bottom_bar = _build_map_help_bar(t)
    map_host, map_card = _build_map_host_stack(
        map_content,
        top_bar,
        left_toolbar,
        right_toolbar,
        bottom_bar,
        sync_map_size,
    )
    toolbar = top_bar

    side = _build_region_side_panel(
        t=t,
        translate=translate,
        add_marker_callback=add_marker_callback,
        delete_marker_callback=delete_marker_callback,
        on_fill_nbt=on_fill_nbt,
        on_delete_region=on_delete_region,
    )
    left_panel = ft.Container(content=map_host, expand=True)
    side_panel = ft.Container(
        content=ft.Column(
            [
                side["selection_panel"],
                side["stats_panel"],
                side["marker_panel"],
                card(side["legend_container"], padding=8),
                side["action_panel"],
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=280,
        expand=False,
    )
    layout = ft.Row(
        [left_panel, side_panel],
        spacing=8,
        expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    return RegionTabChrome(
        layout=layout,
        dimension_dropdown=dimension_dropdown,
        display_mode_dropdown=display_mode_dropdown,
        search_field=search_field,
        search_button=search_button,
        coord_button=coord_button,
        empty_button=empty_button,
        marker_button=marker_button,
        fullscreen_button=fullscreen_button,
        add_marker_button=side["add_marker_button"],
        delete_marker_button=side["delete_marker_button"],
        marker_list=side["marker_list"],
        marker_count_text=side["marker_count_text"],
        help_text=help_text,
        stats_text=side["stats_text"],
        status_text=side["status_text"],
        legend_container=side["legend_container"],
        toolbar=toolbar,
        map_host=map_host,
        map_card=map_card,
        left_panel=left_panel,
        side_panel=side_panel,
    )


def _build_region_side_panel(
    *,
    t: Translate,
    translate: Optional[Translate],
    add_marker_callback: EventCallback,
    delete_marker_callback: EventCallback,
    on_fill_nbt: EventCallback,
    on_delete_region: EventCallback,
) -> dict[str, Any]:
    """Right-side selection/stats/marker/legend/action panels."""
    stats_text = ft.Text(
        t("map.waiting", "等待设置当前存档..."),
        size=11,
        color=THEME.text_muted,
    )
    status_text = ft.Text(
        t("map.select_hint", "点击地图查看区域详情"),
        size=12,
        color=THEME.text_secondary,
        selectable=True,
    )
    marker_count_text = ft.Text(
        t("map.marker_count_empty", "0 个标记"),
        size=11,
        color=THEME.text_muted,
    )
    marker_list = ft.ListView(
        controls=[],
        spacing=3,
        height=150,
        padding=0,
    )
    add_marker_button = ft.IconButton(
        icon=ft.Icons.ADD_LOCATION_ALT,
        icon_color=THEME.success,
        tooltip=t("map.add_marker", "添加标记"),
        on_click=add_marker_callback,
    )
    delete_marker_button = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE,
        icon_color=THEME.error,
        tooltip=t("map.delete_marker", "删除选中标记"),
        disabled=True,
        on_click=delete_marker_callback,
    )
    selection_panel = card(
        ft.Column(
            [
                ft.Text(
                    t("map.selection", "选区"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                status_text,
            ],
            spacing=5,
        ),
        padding=8,
    )
    stats_panel = card(
        ft.Column(
            [
                ft.Text(
                    t("map.overview", "地图概况"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                stats_text,
            ],
            spacing=5,
        ),
        padding=8,
    )
    marker_panel = card(
        ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(ft.Icons.LOCATION_ON, size=16, color=THEME.mc_gold),
                        ft.Text(
                            t("map.markers", "地图标记"),
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary,
                        ),
                        ft.Container(expand=True),
                        marker_count_text,
                        add_marker_button,
                        delete_marker_button,
                    ],
                    spacing=3,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                marker_list,
            ],
            spacing=5,
        ),
        padding=8,
    )
    legend_container = ft.Container(content=build_region_legend_content(translate))
    action_panel = card(
        ft.Column(
            [
                ft.Text(
                    t("map.region_actions", "区域操作"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                ft.Row(
                    [
                        btn_ghost(
                            t("map.fill_nbt", "填入 NBT"),
                            width=100,
                            on_click=on_fill_nbt,
                        ),
                        btn_danger(
                            t("map.delete_region", "删除区域"),
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
    return {
        "stats_text": stats_text,
        "status_text": status_text,
        "marker_count_text": marker_count_text,
        "marker_list": marker_list,
        "add_marker_button": add_marker_button,
        "delete_marker_button": delete_marker_button,
        "selection_panel": selection_panel,
        "stats_panel": stats_panel,
        "marker_panel": marker_panel,
        "legend_container": legend_container,
        "action_panel": action_panel,
    }
