"""Explorer View - 存档浏览器主视图"""
import threading
import flet as ft
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Tuple, Union
from pathlib import Path

from app.ui.theme import THEME
from app.ui.icons import IconSet
from app.ui.components.layout import TabSpec, page_header, panel, segmented_tab_bar

if TYPE_CHECKING:
    from app.application import Application

from core.omni.world_session import WorldSession
from app.services.region_map_service import get_region_map_service

from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.world_info_tab import WorldInfoTabMixin
from app.ui.views.explorer.player_tab import PlayerTabMixin
from app.ui.views.explorer.region_tab import RegionTabMixin
from app.ui.views.explorer.stats_tab import StatsTabMixin
from app.ui.views.explorer.nbt_tab import NbtTabMixin
from app.ui.views.entity_block_search import EntityBlockSearchView
from app.ui.views.explorer.explorer_helpers import (
    tag_display_value,
    coerce_like_tag,
    world_coords_to_region_chunk,
)


class ExplorerView(
        WorldInfoTabMixin,
        PlayerTabMixin,
        RegionTabMixin,
        StatsTabMixin,
        NbtTabMixin,
        ft.Column):
    """存档浏览器视图"""

    def __init__(self, app: "Application") -> None:
        super().__init__(spacing=0)
        self.expand = True
        self.app: "Application" = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._current_player_data: Optional[Any] = None
        self._current_nbt_target: Optional[Union[str, Path]] = None
        self._current_nbt_label = "未加载 NBT"
        self._current_edit_format = "nbt"
        self._nbt_target_options: Dict[str, Path] = {}
        self._last_chunk_objects: List[Dict[str, Any]] = []
        self._staged_nbt_changes: List[Dict[str, Any]] = []
        self._map_service = get_region_map_service()
        self._current_dimension = "overworld"
        self._dimension_region_dirs: Dict[str, str] = {}
        self._selected_region_coord: Optional[Tuple[int, int]] = None
        self._map_view: Optional[Any] = None
        self._compact_mode = False
        self._build()

    @property
    def _t(self):
        return self.app._t

    def _build(self) -> None:
        self.controls.clear()

        self._world_label = ft.Text(
            "未设置当前存档", size=12, color=THEME.text_muted,
        )
        toolbar = page_header("存档浏览器", self._world_label, icon=IconSet.EXPLORE)

        # 标签页容器 - 优化：使用懒加载
        self._tab_world_info = ft.Container()
        self._tab_world_info.expand = True
        self._tab_player = ft.Container()
        self._tab_player.expand = True
        self._tab_region = ft.Container()
        self._tab_region.expand = True
        self._tab_stats = ft.Container()
        self._tab_stats.expand = True
        self._tab_search = ft.Container()
        self._tab_search.expand = True
        self._tab_nbt = ft.Container()
        self._tab_nbt.expand = True
        self._region_display_mode = "activity"

        self._tabs_content = [
            self._tab_world_info,
            self._tab_player,
            self._tab_region,
            self._tab_stats,
            self._tab_search,
            self._tab_nbt
        ]
        self._tab_index = 0

        # 追踪哪些标签页已构建
        self._tabs_built = [False] * 6

        self._tab_bar, self._tab_labels_row, self._tab_buttons, self._tab_labels_widgets = segmented_tab_bar(
            [
                TabSpec("存档信息", IconSet.EARTH), TabSpec("玩家", IconSet.PERSON), TabSpec("地图", IconSet.GRID), TabSpec("统计", IconSet.STATS), TabSpec("搜索", IconSet.SEARCH), TabSpec("NBT", IconSet.DOCUMENT), ], selected_index=0, on_select=self._switch_tab, )
        self._content_box = panel(
            content=self._tabs_content[0],
            padding=10,
        )
        self._content_box.expand = True

        self.controls.append(toolbar)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)

        # 只构建第一个标签页
        self._build_world_info_tab()
        self._tabs_built[0] = True

    def _switch_tab(self, index: int) -> None:
        try:
            # 懒加载标签页
            if not self._tabs_built[index]:
                if index == 1:
                    self._build_player_tab()
                    self._refresh_player_list()
                elif index == 2:
                    self._build_region_tab()
                    self._update_dimension_list()
                    self._refresh_map()
                elif index == 3:
                    self._build_stats_tab()
                elif index == 4:
                    self._build_search_tab()
                elif index == 5:
                    self._build_nbt_tab()
                    self._update_nbt_target_options()
                    self._update_nbt_stage_status()
                    if self.current_uuid:
                        self._load_player_data(self.current_uuid)
                self._tabs_built[index] = True

            self._tab_index = index
            for i, lbl in enumerate(self._tab_labels_widgets):
                selected = i == index
                lbl.color = THEME.text_primary if selected else THEME.text_secondary
                if i < len(self._tab_buttons):
                    self._tab_buttons[i].bgcolor = THEME.mc_stone if selected else THEME.bg_secondary
            self._content_box.content = self._tabs_content[index]
            safe_update(self._content_box)
            safe_update(self._tab_bar)
        except Exception as e:
            self.app.handle_exception(e)

    _tag_display_value = staticmethod(tag_display_value)
    _coerce_like_tag = staticmethod(coerce_like_tag)
    _world_coords_to_region_chunk = staticmethod(world_coords_to_region_chunk)

    def set_compact_mode(self, compact: bool) -> None:
        if self._compact_mode == compact:
            return
        self._compact_mode = compact
        try:
            tab_width = 68 if compact else 88
            tab_height = 52 if compact else 60
            for idx, btn in enumerate(self._tab_buttons):
                btn.width = tab_width
                btn.height = tab_height
                btn.padding = ft.Padding(
                    left=4, right=4, top=4, bottom=4) if compact else ft.Padding(
                    left=6, right=6, top=6, bottom=6)
                if idx < len(self._tab_labels_widgets):
                    self._tab_labels_widgets[idx].size = 10 if compact else 12
            self._tab_labels_row.spacing = 4 if compact else 8
            self._tab_bar.padding = ft.Padding(
                left=6, right=6, top=6, bottom=6) if compact else ft.Padding(
                left=10, right=10, top=10, bottom=10)
            self._content_box.padding = ft.Padding(
                left=6, right=6, top=6, bottom=6) if compact else ft.Padding(
                left=10, right=10, top=10, bottom=10)
            if hasattr(self, '_player_left_panel'):
                self._player_left_panel.width = 300 if compact else 340
            if hasattr(self, '_region_side_panel'):
                self._region_side_panel.width = 240 if compact else 280
            if self._map_view is not None and hasattr(
                    self._map_view, 'resize_map'):
                # Prefer expand/on_resize; only seed a larger fallback size.
                self._map_view.resize_map(
                    700 if compact else 900, 420 if compact else 560)
            safe_update(self)
        except Exception as ex:
            self.app.handle_exception(ex, title="设置紧凑模式失败")

    def _build_search_tab(self) -> None:
        self._entity_block_search_view = EntityBlockSearchView(
            self.app, compact=True)
        self._tab_search.content = self._entity_block_search_view

    def on_save_selected(self, path: str) -> None:
        """当存档被选择时调用（从侧边栏）"""
        self._load_world(path)
        if hasattr(self, "_entity_block_search_view"):
            self._entity_block_search_view.on_save_selected(path)

    def _start_entity_block_search(self, e: Any = None) -> None:
        """启动实体/方块搜索"""
        if hasattr(self, "_entity_block_search_view"):
            self._switch_tab(4)

    def _load_world(self, path: Any = None) -> None:
        """加载世界存档"""
        try:
            if path is None or hasattr(path, "control"):
                path = getattr(self.app, "_current_save_path", None)
            if not path:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return

            # 显示加载状态
            self._world_label.value = "⏳ 正在加载存档..."
            self._world_label.color = THEME.mc_gold
            safe_update(self._world_label)

            # 后台线程加载 WorldSession，避免阻塞 UI
            def _load():
                try:
                    session = WorldSession(Path(path), log=self.app.log)

                    async def _apply_loaded_world(
                            loaded_session: WorldSession):
                        try:
                            self._populate_world(loaded_session)
                        except Exception as ui_ex:
                            self.app.handle_exception(ui_ex, title="更新存档界面失败")
                    self.app.page.run_task(_apply_loaded_world, session)
                except FileNotFoundError as ex:
                    async def _show_error(err_msg: str):
                        self._world_label.value = "❌ 无效的存档目录"
                        self._world_label.color = THEME.error
                        safe_update(self._world_label)
                        self.app.error_dialog(
                            "无效的存档", f"所选目录不是有效的 Minecraft 存档：\n\n{err_msg}\n\n请确保选择包含 level.dat 的存档根目录")
                    self.app.page.run_task(_show_error, str(ex))
                except RuntimeError as ex:
                    async def _show_nbt_error(err_msg: str):
                        self._world_label.value = "❌ NBT 解析失败"
                        self._world_label.color = THEME.error
                        safe_update(self._world_label)
                        self.app.error_dialog(
                            "NBT 解析失败",
                            f"level.dat 文件损坏或格式不兼容：\n\n{err_msg}\n\n可能原因：\n• 存档文件损坏\n• 不支持的 Minecraft 版本\n• 文件被其他程序占用")
                    self.app.page.run_task(_show_nbt_error, str(ex))
                except Exception as ex:
                    async def _show_general_error(err_msg: str, err_type: str):
                        self._world_label.value = "❌ 加载存档失败"
                        self._world_label.color = THEME.warning
                        safe_update(self._world_label)
                        self.app.error_dialog(
                            "加载存档失败", f"{err_type}: {err_msg}")
                    self.app.page.run_task(
                        _show_general_error, str(ex), type(ex).__name__)

            threading.Thread(target=_load, daemon=True).start()
        except Exception as ex:
            self.app.handle_exception(ex, title="设置当前存档失败")

    def _populate_world(self, session: WorldSession) -> None:
        """在 WorldSession 加载完成后填充 UI（可在后台线程调用）"""
        self.world_session = session
        self._world_label.value = f"当前存档: {session.world_path.name}"
        self._world_label.color = THEME.text_muted
        self._current_nbt_target = None
        self._current_nbt_label = "未加载 NBT"
        self._staged_nbt_changes.clear()
        self._update_nbt_target_options()
        self._update_nbt_stage_status()
        safe_update(self._world_label)

        # 更新存档信息面板
        world_info = session.get_world_info()
        dimensions = session.get_dimensions()
        stats = {
            "world_path": str(session.world_path),
            "player_count": len(session.get_player_uuids()),
            "region_count": len(session._region_files),
            "dimension_count": len(dimensions),
        }
        self._world_info_panel.update_info(world_info, stats=stats)

        self._refresh_player_list()

        # 扫描并填充维度列表
        self._update_dimension_list()

        if hasattr(self, "_region_stats_text") and self._map_view is not None:
            self._refresh_map()
