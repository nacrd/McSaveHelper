"""Three-panel UI composition for the Explorer NBT tab."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft

from app.ui.components.buttons import btn_ghost, btn_primary
from app.ui.components.fields import text_field
from app.ui.theme import THEME
from app.ui.views.explorer.nbt_tree import NBTTreeView

Callback = Callable[..., None]


@dataclass(frozen=True)
class NbtTabCallbacks:
    """NBT 页左侧/工具栏动作回调集合（由 Tab 控制器注入）。"""

    load_target: Callback
    load_player: Callback
    load_level: Callback
    load_chunk: Callback
    fill_world_coords: Callback
    load_world_coords: Callback
    query_block: Callback
    replace_block: Callback
    filter_chunk_objects: Callback
    search: Callback
    expand_all: Callback
    collapse_all: Callback
    export_json: Callback
    stage_change: Callback
    commit: Callback
    discard: Callback


@dataclass(frozen=True)
class NbtTabChrome:
    """NBT 三栏布局构建结果：根容器与需后续绑定的控件引用。"""

    root: ft.Container
    left_panel: ft.Container
    center_panel: ft.Container
    right_panel: ft.Container
    target_dropdown: ft.Dropdown
    region_file_field: Any
    chunk_x_field: Any
    chunk_z_field: Any
    world_x_field: Any
    world_z_field: Any
    block_y_field: Any
    block_query_result: ft.Text
    block_replace_name_field: Any
    chunk_objects_list: ft.Column
    target_label: ft.Text
    nbt_tree: NBTTreeView
    stage_status: ft.Text
    stage_list: ft.Column


@dataclass(frozen=True)
class _LeftPanel:
    """左侧目标选择与方块查询面板的内部组装结果。"""

    panel: ft.Container
    target_dropdown: ft.Dropdown
    region_file_field: Any
    chunk_x_field: Any
    chunk_z_field: Any
    world_x_field: Any
    world_z_field: Any
    block_y_field: Any
    block_query_result: ft.Text
    block_replace_name_field: Any
    chunk_objects_list: ft.Column


@dataclass(frozen=True)
class _CenterPanel:
    """中间 NBT 树与目标标签面板。"""

    panel: ft.Container
    target_label: ft.Text
    nbt_tree: NBTTreeView


@dataclass(frozen=True)
class _RightPanel:
    """右侧暂存变更列表与状态文本。"""

    panel: ft.Container
    stage_status: ft.Text
    stage_list: ft.Column


def build_nbt_tab_chrome(
    *,
    current_label: str,
    callbacks: NbtTabCallbacks,
) -> NbtTabChrome:
    """Build all three NBT panels and return their stable control references."""
    left = _build_left_panel(callbacks)
    center = _build_center_panel(current_label, callbacks)
    right = _build_right_panel(callbacks)
    root = ft.Container(
        content=ft.Row(
            [left.panel, center.panel, right.panel],
            spacing=8,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        padding=10,
        expand=True,
    )
    return NbtTabChrome(
        root=root,
        left_panel=left.panel,
        center_panel=center.panel,
        right_panel=right.panel,
        target_dropdown=left.target_dropdown,
        region_file_field=left.region_file_field,
        chunk_x_field=left.chunk_x_field,
        chunk_z_field=left.chunk_z_field,
        world_x_field=left.world_x_field,
        world_z_field=left.world_z_field,
        block_y_field=left.block_y_field,
        block_query_result=left.block_query_result,
        block_replace_name_field=left.block_replace_name_field,
        chunk_objects_list=left.chunk_objects_list,
        target_label=center.target_label,
        nbt_tree=center.nbt_tree,
        stage_status=right.stage_status,
        stage_list=right.stage_list,
    )


def _build_left_panel(callbacks: NbtTabCallbacks) -> _LeftPanel:
    target_dropdown, data_source = _build_nbt_data_source_section(callbacks)
    (
        region_file_field,
        chunk_x_field,
        chunk_z_field,
        world_x_field,
        world_z_field,
        chunk_section,
    ) = _build_nbt_chunk_section(callbacks)
    (
        block_y_field,
        block_query_result,
        block_replace_name_field,
        block_section,
    ) = _build_nbt_block_section(callbacks)
    chunk_objects_list, chunk_objects = _build_nbt_chunk_objects_section(
        callbacks
    )
    content = ft.Column(
        [
            data_source,
            ft.Divider(height=1, color=THEME.border_light),
            chunk_section,
            ft.Divider(height=1, color=THEME.border_light),
            block_section,
            ft.Divider(height=1, color=THEME.border_light),
            chunk_objects,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )
    panel = ft.Container(
        content=content,
        width=280,
        bgcolor=THEME.bg_card,
        border=ft.Border.all(1, THEME.border_light),
        border_radius=8,
        padding=12,
    )
    return _LeftPanel(
        panel=panel,
        target_dropdown=target_dropdown,
        region_file_field=region_file_field,
        chunk_x_field=chunk_x_field,
        chunk_z_field=chunk_z_field,
        world_x_field=world_x_field,
        world_z_field=world_z_field,
        block_y_field=block_y_field,
        block_query_result=block_query_result,
        block_replace_name_field=block_replace_name_field,
        chunk_objects_list=chunk_objects_list,
    )


def _build_nbt_data_source_section(
    callbacks: NbtTabCallbacks,
) -> tuple[ft.Dropdown, ft.Column]:
    target_dropdown = ft.Dropdown(
        label="NBT 目标",
        options=[],
        width=250,
        border_color=THEME.border_standard,
        text_size=12,
        on_select=callbacks.load_target,
    )
    quick_load_buttons = ft.Row(
        [
            ft.Container(
                content=btn_ghost(
                    "玩家",
                    on_click=callbacks.load_player,
                    height=32,
                ),
                expand=True,
            ),
            ft.Container(
                content=btn_ghost(
                    "世界",
                    on_click=callbacks.load_level,
                    height=32,
                ),
                expand=True,
            ),
        ],
        spacing=6,
    )
    data_source = ft.Column(
        [
            ft.Text(
                "📁 数据源",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            target_dropdown,
            quick_load_buttons,
        ],
        spacing=8,
    )
    return target_dropdown, data_source


def _build_nbt_chunk_section(
    callbacks: NbtTabCallbacks,
) -> tuple[
    ft.Control,
    ft.Control,
    ft.Control,
    ft.Control,
    ft.Control,
    ft.Column,
]:
    region_file_field, chunk_x_field, chunk_z_field = _nbt_chunk_file_fields()
    world_x_field, world_z_field = _nbt_world_coord_fields()
    chunk_section = ft.Column(
        [
            ft.Text(
                "📦 区块",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            region_file_field,
            ft.Row([chunk_x_field, chunk_z_field], spacing=6),
            ft.Container(
                content=btn_ghost(
                    "加载区块",
                    on_click=callbacks.load_chunk,
                    height=32,
                ),
                expand=True,
            ),
            ft.Text("世界坐标", size=11, color=THEME.text_muted),
            ft.Row([world_x_field, world_z_field], spacing=6),
            ft.Row(
                [
                    btn_ghost(
                        "填入",
                        on_click=callbacks.fill_world_coords,
                        height=30,
                    ),
                    btn_primary(
                        "定位加载",
                        on_click=callbacks.load_world_coords,
                        height=30,
                    ),
                ],
                spacing=6,
            ),
        ],
        spacing=6,
    )
    return (
        region_file_field,
        chunk_x_field,
        chunk_z_field,
        world_x_field,
        world_z_field,
        chunk_section,
    )


def _nbt_chunk_file_fields() -> tuple[ft.Control, ft.Control, ft.Control]:
    region_file_field = text_field(
        label="区域文件",
        hint_text="region/r.0.0.mca",
        width=250,
        expand=False,
    )
    chunk_x_field = text_field(
        value="0",
        label="区块X",
        width=80,
        expand=False,
    )
    chunk_z_field = text_field(
        value="0",
        label="区块Z",
        width=80,
        expand=False,
    )
    return region_file_field, chunk_x_field, chunk_z_field


def _nbt_world_coord_fields() -> tuple[ft.Control, ft.Control]:
    world_x_field = text_field(
        value="0",
        label="世界X",
        width=80,
        expand=False,
    )
    world_z_field = text_field(
        value="0",
        label="世界Z",
        width=80,
        expand=False,
    )
    return world_x_field, world_z_field


def _build_nbt_block_section(
    callbacks: NbtTabCallbacks,
) -> tuple[ft.Control, ft.Text, ft.Control, ft.Column]:
    block_y_field = text_field(
        value="64",
        label="Y",
        width=60,
        expand=False,
    )
    block_query_result = ft.Text(
        "",
        size=10,
        color=THEME.text_muted,
        max_lines=2,
    )
    block_replace_name_field = text_field(
        label="方块ID",
        hint_text="stone",
        width=250,
        expand=False,
    )
    block_section = ft.Column(
        [
            ft.Text(
                "🧱 方块",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            ft.Row(
                [
                    block_y_field,
                    btn_ghost(
                        "查询",
                        on_click=callbacks.query_block,
                        height=30,
                    ),
                ],
                spacing=6,
            ),
            block_query_result,
            block_replace_name_field,
            ft.Container(
                content=btn_primary(
                    "替换",
                    on_click=callbacks.replace_block,
                    height=32,
                ),
                expand=True,
            ),
        ],
        spacing=6,
    )
    return (
        block_y_field,
        block_query_result,
        block_replace_name_field,
        block_section,
    )


def _build_nbt_chunk_objects_section(
    callbacks: NbtTabCallbacks,
) -> tuple[ft.Column, ft.Column]:
    chunk_objects_list = ft.Column(spacing=4)
    chunk_objects = ft.Column(
        [
            ft.Text(
                "区块对象",
                size=13,
                weight=ft.FontWeight.BOLD,
                color=THEME.text_primary,
            ),
            text_field(
                label="筛选",
                hint_text="实体或方块实体",
                width=250,
                expand=False,
                on_change=callbacks.filter_chunk_objects,
            ),
            chunk_objects_list,
        ],
        spacing=6,
    )
    return chunk_objects_list, chunk_objects


def _build_center_panel(
    current_label: str,
    callbacks: NbtTabCallbacks,
) -> _CenterPanel:
    target_label = ft.Text(
        current_label,
        size=12,
        color=THEME.text_secondary,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    search_field = text_field(
        label="搜索",
        hint_text="字段/值",
        width=200,
        expand=False,
        on_change=callbacks.search,
    )
    toolbar = ft.Row(
        [
            target_label,
            ft.Container(expand=True),
            search_field,
            btn_ghost("展开", on_click=callbacks.expand_all, height=32),
            btn_ghost("折叠", on_click=callbacks.collapse_all, height=32),
            btn_ghost("导出", on_click=callbacks.export_json, height=32),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    nbt_tree = NBTTreeView(on_stage_change=callbacks.stage_change)
    tree_container = ft.Container(
        content=nbt_tree,
        bgcolor=THEME.bg_secondary,
        border_radius=4,
        padding=4,
        expand=True,
    )
    panel = ft.Container(
        content=ft.Column(
            [toolbar, tree_container],
            spacing=8,
            expand=True,
        ),
        expand=True,
        bgcolor=THEME.bg_card,
        border=ft.Border.all(1, THEME.border_light),
        border_radius=8,
        padding=12,
    )
    return _CenterPanel(
        panel=panel,
        target_label=target_label,
        nbt_tree=nbt_tree,
    )


def _build_right_panel(callbacks: NbtTabCallbacks) -> _RightPanel:
    stage_status = ft.Text(
        "暂存区: 0 个变更",
        size=12,
        weight=ft.FontWeight.BOLD,
        color=THEME.text_muted,
    )
    stage_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)
    actions = ft.Row(
        [
            btn_primary("提交", on_click=callbacks.commit, height=36),
            btn_ghost("丢弃", on_click=callbacks.discard, height=36),
        ],
        spacing=6,
    )
    panel = ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "📋 暂存区",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary,
                ),
                stage_status,
                ft.Divider(height=1, color=THEME.border_light),
                ft.Container(content=stage_list, expand=True),
                actions,
            ],
            spacing=8,
            expand=True,
        ),
        width=300,
        bgcolor=THEME.bg_card,
        border=ft.Border.all(1, THEME.border_light),
        border_radius=8,
        padding=12,
    )
    return _RightPanel(
        panel=panel,
        stage_status=stage_status,
        stage_list=stage_list,
    )
