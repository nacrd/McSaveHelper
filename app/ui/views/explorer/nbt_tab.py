"""NBT tab mixin for ExplorerView - 三栏布局版本"""
from typing import Any, Union, List
from pathlib import Path

import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_ghost
from app.ui.components.fields import text_field
from app.ui.components.cards import card
from app.ui.components.layout import section_header
from app.ui.views.explorer.nbt_tree import NBTTreeView
from app.ui.views.explorer.nbt import (
    NbtDataLoader,
    NbtStageManager,
    ChunkOperations,
    NbtCommitHandler,
)


class NbtTabMixin:
    """NBT 页签主协调器 - 三栏布局：左侧导航 + 中央查看器 + 右侧暂存区"""

    def _build_nbt_tab(self) -> None:
        """构建 NBT 页签 UI - 三栏布局"""
        # 初始化功能模块
        self._data_loader = NbtDataLoader(self)
        self._stage_manager = NbtStageManager(self)
        self._chunk_ops = ChunkOperations(self)
        self._commit_handler = NbtCommitHandler(self)

        # 初始化折叠状态
        self._nbt_left_collapsed = False
        self._nbt_right_collapsed = False

        # ========== 左侧导航面板 ==========
        left_panel = self._build_left_navigation_panel()

        # ========== 中央 NBT 查看器 ==========
        center_panel = self._build_center_viewer_panel()

        # ========== 右侧暂存区面板 ==========
        right_panel = self._build_right_stage_panel()

        # ========== 主布局：三栏 ==========
        main_row = ft.Row(
            [left_panel, center_panel, right_panel],
            spacing=8,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

        self._tab_nbt.content = ft.Container(
            content=main_row,
            padding=10,
            expand=True,
        )

    # ==================== 左侧导航面板 ====================

    def _build_left_navigation_panel(self) -> ft.Container:
        """构建左侧导航面板 - 包含数据源、区块、方块操作"""
        # 数据源下拉框
        self._nbt_target_dropdown = ft.Dropdown(
            label="NBT 目标",
            options=[],
            width=250,
            border_color=THEME.border_standard,
            text_size=12,
            on_select=self._load_selected_nbt_target,
        )

        # 快速加载按钮
        quick_load_buttons = ft.Row(
            [
                ft.Container(
                    content=btn_ghost(
                        "玩家",
                        on_click=self._load_current_player_nbt,
                        height=32),
                    expand=True),
                ft.Container(
                    content=btn_ghost(
                        "世界",
                        on_click=self._load_level_nbt,
                        height=32),
                    expand=True),
            ],
            spacing=6)

        # 数据源区域
        data_source_section = ft.Column([
            ft.Text("📁 数据源", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._nbt_target_dropdown,
            quick_load_buttons,
        ], spacing=8)

        # 区块坐标输入
        self._region_file_field = text_field(
            label="区域文件", hint_text="region/r.0.0.mca",
            width=250, expand=False,
        )
        self._chunk_x_field = text_field(
            value="0", label="区块X", width=80, expand=False)
        self._chunk_z_field = text_field(
            value="0", label="区块Z", width=80, expand=False)
        self._world_x_field = text_field(
            value="0", label="世界X", width=80, expand=False)
        self._world_z_field = text_field(
            value="0", label="世界Z", width=80, expand=False)

        chunk_section = ft.Column([
            ft.Text("📦 区块", size=13, weight=ft.FontWeight.BOLD, color=THEME.text_primary),
            self._region_file_field,
            ft.Row([self._chunk_x_field, self._chunk_z_field], spacing=6),
            ft.Container(content=btn_ghost("加载区块", on_click=self._load_chunk_nbt, height=32), expand=True),
            ft.Text("世界坐标", size=11, color=THEME.text_muted),
            ft.Row([self._world_x_field, self._world_z_field], spacing=6),
            ft.Row([
                btn_ghost("填入", on_click=self._fill_chunk_from_world_coords, height=30),
                btn_primary("定位加载", on_click=self._load_chunk_from_world_coords, height=30),
            ], spacing=6),
        ], spacing=6)

        # 方块操作
        self._block_y_field = text_field(
            value="64", label="Y", width=60, expand=False)
        self._block_query_result = ft.Text(
            "", size=10, color=THEME.text_muted, max_lines=2)
        self._block_replace_name_field = text_field(
            label="方块ID", hint_text="stone",
            width=250, expand=False,
        )

        block_section = ft.Column([ft.Text("🧱 方块",
                                           size=13,
                                           weight=ft.FontWeight.BOLD,
                                           color=THEME.text_primary),
                                   ft.Row([self._block_y_field,
                                           btn_ghost("查询",
                                                     on_click=self._query_block_at_current_coords,
                                                     height=30),
                                           ],
                                          spacing=6),
                                   self._block_query_result,
                                   self._block_replace_name_field,
                                   ft.Container(content=btn_primary("替换",
                                                                    on_click=self._replace_block_at_current_coords,
                                                                    height=32),
                                                expand=True),
                                   ],
                                  spacing=6)

        # 左侧面板容器
        left_content = ft.Column(
            [
                data_source_section,
                ft.Divider(height=1, color=THEME.border_light),
                chunk_section,
                ft.Divider(height=1, color=THEME.border_light),
                block_section,
            ],
            spacing=12,
            scroll=ft.ScrollMode.AUTO,
        )

        self._nbt_left_panel = ft.Container(
            content=left_content,
            width=280,
            bgcolor=THEME.bg_card,
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

        return self._nbt_left_panel

    # ==================== 中央查看器面板 ====================

    def _build_center_viewer_panel(self) -> ft.Container:
        """构建中央 NBT 查看器面板"""
        # 顶部工具栏
        self._nbt_target_label = ft.Text(
            self._current_nbt_label, size=12, color=THEME.text_secondary,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        )

        nbt_search_field = text_field(
            label="搜索", hint_text="字段/值",
            width=200, expand=False,
            on_change=self._on_nbt_search,
        )

        toolbar = ft.Row([
            self._nbt_target_label,
            ft.Container(expand=True),
            nbt_search_field,
            btn_ghost("展开", on_click=self._expand_all_nbt, height=32),
            btn_ghost("折叠", on_click=self._collapse_all_nbt, height=32),
            btn_ghost("导出", on_click=self._export_nbt_json, height=32),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        # NBT 树
        self._nbt_tree = NBTTreeView(on_stage_change=self._stage_nbt_change)

        tree_container = ft.Container(
            content=self._nbt_tree,
            bgcolor=THEME.bg_secondary,
            border_radius=4,
            padding=4,
            expand=True,
        )

        # 中央面板
        center_content = ft.Column(
            [toolbar, tree_container],
            spacing=8,
            expand=True,
        )

        self._nbt_center_panel = ft.Container(
            content=center_content,
            expand=True,
            bgcolor=THEME.bg_card,
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

        return self._nbt_center_panel

    # ==================== 右侧暂存区面板 ====================

    def _build_right_stage_panel(self) -> ft.Container:
        """构建右侧暂存区面板"""
        # 暂存区状态
        self._nbt_stage_status = ft.Text(
            "暂存区: 0 个变更",
            size=12,
            weight=ft.FontWeight.BOLD,
            color=THEME.text_muted,
        )

        # 暂存列表
        self._nbt_stage_list = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO)

        # 操作按钮
        action_buttons = ft.Row([
            btn_primary("提交", on_click=self._commit_nbt_changes, height=36),
            btn_ghost("丢弃", on_click=self._discard_nbt_changes, height=36),
        ], spacing=6)

        # 右侧面板
        right_content = ft.Column(
            [
                ft.Text(
                    "📋 暂存区",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_primary),
                self._nbt_stage_status,
                ft.Divider(
                    height=1,
                    color=THEME.border_light),
                ft.Container(
                    content=self._nbt_stage_list,
                    expand=True),
                action_buttons,
            ],
            spacing=8,
            expand=True,
        )

        self._nbt_right_panel = ft.Container(
            content=right_content,
            width=300,
            bgcolor=THEME.bg_card,
            border=ft.border.all(1, THEME.border_light),
            border_radius=8,
            padding=12,
        )

        return self._nbt_right_panel

    # ========== 折叠功能（预留） ==========

    def _toggle_left_panel(self, e: Any = None) -> None:
        """切换左侧面板显示/隐藏"""
        self._nbt_left_collapsed = not self._nbt_left_collapsed
        self._nbt_left_panel.visible = not self._nbt_left_collapsed
        self._nbt_left_panel.update()

    def _toggle_right_panel(self, e: Any = None) -> None:
        """切换右侧面板显示/隐藏"""
        self._nbt_right_collapsed = not self._nbt_right_collapsed
        self._nbt_right_panel.visible = not self._nbt_right_collapsed
        self._nbt_right_panel.update()

    # ========== 以下是委托方法（与之前相同） ==========

    def _expand_all_nbt(self, e: Any = None) -> None:
        try:
            self._nbt_tree.expand_all(show_all_children=True)
        except Exception as ex:
            self.app.handle_exception(ex, title="展开全部 NBT 失败")

    def _collapse_all_nbt(self, e: Any = None) -> None:
        try:
            self._nbt_tree.collapse_all()
        except Exception as ex:
            self.app.handle_exception(ex, title="折叠全部 NBT 失败")

    def _on_nbt_search(self, e: Any) -> None:
        try:
            self._nbt_tree.search(e.control.value or "")
        except Exception as ex:
            self.app.handle_exception(ex, title="搜索 NBT 失败")

    def _update_nbt_target_options(self) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.update_nbt_target_options()

    def _load_current_player_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_current_player_nbt(e)

    def _load_level_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_level_nbt(e)

    def _load_selected_nbt_target(self, e: Any) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_selected_nbt_target(e)

    def _load_chunk_nbt(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_chunk_nbt(e)

    def _fill_chunk_from_world_coords(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.fill_chunk_from_world_coords(e)

    def _load_chunk_from_world_coords(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.load_chunk_from_world_coords(e)

    def _export_nbt_json(self, e: Any = None) -> None:
        if hasattr(self, '_data_loader'):
            self._data_loader.export_nbt_json(e)

    def _stage_nbt_change(self,
                          path_parts: List[Union[str,
                                                 int]],
                          old_value: Any,
                          new_value: Any,
                          display_path: str) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.stage_change(
                path_parts, old_value, new_value, display_path)

    def _update_nbt_stage_status(self) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.update_stage_status()

    def _unstage_nbt_change(self, index: int) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.unstage_change(index)

    def _discard_nbt_changes(self, e: Any = None) -> None:
        if hasattr(self, '_stage_manager'):
            self._stage_manager.discard_all_changes(e)

    def _render_chunk_objects(self, chunk_data: Any) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.render_chunk_objects(chunk_data)

    def _on_chunk_object_filter(self, e: Any) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.on_chunk_object_filter(e)

    def _query_block_at_current_coords(
            self, e: Any = None, silent: bool = False) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.query_block_at_current_coords(e, silent)

    def _replace_block_at_current_coords(self, e: Any = None) -> None:
        if hasattr(self, '_chunk_ops'):
            self._chunk_ops.replace_block_at_current_coords(e)

    def _commit_nbt_changes(self, e: Any = None) -> None:
        if hasattr(self, '_commit_handler'):
            self._commit_handler.commit_changes(e)
