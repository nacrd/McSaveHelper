"""Explorer View - 存档浏览器主视图"""
import flet as ft
from typing import Any, Callable, Optional, Dict, Tuple
from pathlib import Path

from app.ui.theme import THEME
from app.ui.theme import TEXT_CAPTION_SIZE, TEXT_SECONDARY_SIZE
from app.models.nbt_edit import (
    NbtStageStore,
)
from app.presenters.nbt_view_state import NbtViewState, clear_nbt_target
from app.ui.icons import IconSet
from app.ui.components.layout import TabSpec, page_header, panel, segmented_tab_bar
from app.ui.view_actions import ViewAction

from core.omni.world_session import WorldSession
from app.ui.views.explorer.utils import safe_update
from app.ui.utils import run_on_ui
from app.ui.views.explorer.world_info_tab import WorldInfoTabMixin
from app.ui.views.explorer.player_tab import PlayerTabMixin
from app.ui.views.explorer.region_tab import RegionTabMixin
from app.ui.views.explorer.stats_tab import StatsTabMixin
from app.ui.views.explorer.nbt_tab import NbtTabMixin
from app.ui.views.explorer.mixin_context import ExplorerHost
from app.ui.views.entity_block_search import EntityBlockSearchView
from app.ui.views.explorer.explorer_helpers import (
    tag_display_value,
    coerce_like_tag,
    world_coords_to_region_chunk,
)
from app.controllers.map_controller import MapController
from app.controllers.region_delete_controller import RegionDeleteController
from app.services.execution_runtime import (
    OperationCancelledError,
    OperationContext,
    TaskPriority,
)
from app.services.map_marker_service import MapMarkerService
from app.services.ui_delivery import UiDeliverySpec
from app.services.world_repository import WorldReadContext


class ExplorerView(
        WorldInfoTabMixin,
        PlayerTabMixin,
        RegionTabMixin,
        StatsTabMixin,
        NbtTabMixin,
        ft.Column):
    """存档浏览器视图"""

    def __init__(self, app: "ExplorerHost") -> None:
        """初始化存档浏览器主视图及其子 Tab 状态。

        Args:
            app: Explorer 各 Tab 所需的显式 UI 与服务端口。
        """
        super().__init__(spacing=0)
        self.expand = True
        self.app = app
        self.world_session: Optional[WorldSession] = None
        self.current_uuid: Optional[str] = None
        self.player_uuid_map: Dict[str, str] = {}
        self._current_player_data: Optional[Any] = None
        self._nbt_view_state = NbtViewState()
        self._nbt_stage_store = NbtStageStore()
        self._map_service = self.app.create_region_map_service()
        self._task_scope = self.app.execution_runtime.create_scope(
            "explorer_view"
        )
        self._world_load_generation = 0
        self._disposed = False
        self._region_delete_controller = RegionDeleteController(
            self._task_scope,
            self.app.world_transactions,
        )
        self._map_controller = MapController(
            MapMarkerService(),
            task_scope=self._task_scope,
            post_to_ui=lambda callback: run_on_ui(self.app.page, callback),
            get_generation=lambda: self._world_load_generation,
        )
        self._current_dimension = "overworld"
        self._dimension_region_dirs: Dict[str, str] = {}
        self._selected_region_coord: Optional[Tuple[int, int]] = None
        self._map_view: Optional[Any] = None
        self._compact_mode = False
        self._build()

    @property
    def _t(self):
        return self.app.translate

    def get_top_actions(self) -> list[ViewAction]:
        """Declare only commands relevant to the selected Explorer tab."""
        actions_by_tab = {
            1: [
                ViewAction(
                    self._t("top_bar.stage_player", "暂存玩家"),
                    self._stage_player_edit_form,
                ),
            ],
            2: [
                ViewAction(
                    self._t("top_bar.refresh_map", "刷新地图"),
                    lambda event: self._refresh_map(),
                ),
                ViewAction(
                    self._t("top_bar.start_export", "开始导出"),
                    self._start_map_export,
                ),
            ],
            3: [
                ViewAction(
                    self._t("top_bar.start_stats", "开始统计"),
                    self._analyze_world_stats,
                ),
            ],
            5: [
                ViewAction(
                    self._t("top_bar.commit_changes", "提交变更"),
                    self._commit_nbt_changes,
                ),
                ViewAction(
                    self._t("top_bar.discard_changes", "丢弃暂存"),
                    self._discard_nbt_changes,
                    "danger",
                ),
            ],
        }
        return actions_by_tab.get(self._tab_index, [])

    def _build(self) -> None:
        self.controls.clear()
        self._world_label = ft.Text(
            "未设置当前存档", size=12, color=THEME.text_muted,
        )
        self._page_header = page_header(
            "存档浏览器",
            self._world_label,
            icon=IconSet.EXPLORE,
        )
        self._init_tab_containers()
        self._build_tab_bar()
        self._content_box = panel(
            content=self._tabs_content[0],
            padding=10,
        )
        self._content_box.expand = True
        self.controls.append(self._page_header)
        col_tabs = ft.Column([self._tab_bar, self._content_box], spacing=8)
        col_tabs.expand = True
        self.controls.append(col_tabs)
        # 只构建第一个标签页
        self._build_world_info_tab()
        self._tabs_built[0] = True

    def _init_tab_containers(self) -> None:
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
            self._tab_nbt,
        ]
        self._tab_index = 0
        self._tabs_built = [False] * 6

    def _build_tab_bar(self) -> None:
        (
            self._tab_bar,
            self._tab_labels_row,
            self._tab_buttons,
            self._tab_labels_widgets,
        ) = segmented_tab_bar(
            [
                TabSpec("存档信息", IconSet.EARTH),
                TabSpec("玩家", IconSet.PERSON),
                TabSpec("地图", IconSet.GRID),
                TabSpec("统计", IconSet.STATS),
                TabSpec("搜索", IconSet.SEARCH),
                TabSpec("NBT", IconSet.DOCUMENT),
            ],
            selected_index=0,
            on_select=self._switch_tab,
        )

    def _switch_tab(self, index: int) -> None:
        try:
            self._build_tab_if_needed(index)
            self._tab_index = index
            self._show_selected_tab(index)
            self.app.view_manager.refresh_current_actions()
        except Exception as e:
            self.app.handle_exception(e)

    def _build_tab_if_needed(self, index: int) -> None:
        """Build the selected lazy tab once before it is shown."""
        if self._tabs_built[index]:
            return
        builders = {
            1: self._build_player_tab_content,
            2: self._build_region_tab_content,
            3: self._build_stats_tab,
            4: self._build_search_tab,
            5: self._build_nbt_tab_content,
        }
        builder = builders.get(index)
        if builder is not None:
            builder()
        self._tabs_built[index] = True

    def _build_player_tab_content(self) -> None:
        self._build_player_tab()
        self._refresh_player_list()

    def _build_region_tab_content(self) -> None:
        self._build_region_tab()
        self._update_dimension_list()
        self._refresh_map()

    def _build_nbt_tab_content(self) -> None:
        self._build_nbt_tab()
        self._update_nbt_target_options()
        self._update_nbt_stage_status()
        if self.current_uuid:
            self._load_player_data(self.current_uuid)

    def _show_selected_tab(self, index: int) -> None:
        for tab_index, label in enumerate(self._tab_labels_widgets):
            selected = tab_index == index
            label.color = THEME.text_primary if selected else THEME.text_secondary
            if tab_index < len(self._tab_buttons):
                button = self._tab_buttons[tab_index]
                button.bgcolor = (
                    THEME.bg_elevated if selected else ft.Colors.TRANSPARENT
                )
                button.border = ft.Border.all(
                    1,
                    THEME.border_standard
                    if selected
                    else ft.Colors.TRANSPARENT,
                )
                if isinstance(button.content, ft.Row):
                    icon = button.content.controls[0]
                    if isinstance(icon, ft.Icon):
                        icon.color = THEME.accent if selected else THEME.text_muted
        self._content_box.content = self._tabs_content[index]
        safe_update(self._content_box)
        safe_update(self._tab_bar)

    _tag_display_value = staticmethod(tag_display_value)
    _coerce_like_tag = staticmethod(coerce_like_tag)
    _world_coords_to_region_chunk = staticmethod(world_coords_to_region_chunk)

    def set_compact_mode(self, compact: bool) -> None:
        """切换紧凑/标准布局密度并调整子面板尺寸。

        Args:
            compact: 为 True 时使用更窄的标签与侧栏。
        """
        if self._compact_mode == compact:
            return
        self._compact_mode = compact
        try:
            tab_width = 82 if compact else 100
            tab_height = 44
            for idx, btn in enumerate(self._tab_buttons):
                btn.width = tab_width
                btn.height = tab_height
                btn.padding = ft.Padding(
                    left=4, right=4, top=4, bottom=4) if compact else ft.Padding(
                    left=6, right=6, top=6, bottom=6)
                if idx < len(self._tab_labels_widgets):
                    self._tab_labels_widgets[idx].size = (
                        TEXT_CAPTION_SIZE
                        if compact
                        else TEXT_SECONDARY_SIZE
                    )
            self._tab_labels_row.spacing = 3 if compact else 4
            self._tab_bar.padding = ft.Padding(
                left=3, right=3, top=3, bottom=3) if compact else ft.Padding(
                    left=4, right=4, top=4, bottom=4)
            self._content_box.padding = ft.Padding(
                left=6, right=6, top=6, bottom=6) if compact else ft.Padding(
                left=10, right=10, top=10, bottom=10)
            if hasattr(self, '_player_left_panel'):
                self._set_player_compact_layout(compact)
            if hasattr(self, '_region_side_panel'):
                self._region_side_panel.width = 240 if compact else 280
            if hasattr(self, '_nbt_root'):
                self._set_nbt_compact_layout(compact)
            if hasattr(self, '_entity_block_search_view'):
                self._entity_block_search_view.set_compact_mode(compact)
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
            self.app,
            compact=self._compact_mode,
        )
        self._tab_search.content = self._entity_block_search_view

    def on_save_selected(self, path: str) -> None:
        """当存档被选择时调用（从侧边栏）"""
        self._load_world(path)
        if hasattr(self, "_entity_block_search_view"):
            self._entity_block_search_view.on_save_selected(path)

    def _start_entity_block_search(self, e: Any = None) -> None:
        """打开实体/方块搜索标签。"""
        self._switch_tab(4)

    def _start_map_export(self, e: Any = None) -> None:
        """打开地图标签并弹出导出对话框。"""
        self._switch_tab(2)
        open_export = getattr(self, "_open_map_export_dialog", None)
        if callable(open_export):
            open_export()

    def _load_world(self, path: Any = None) -> None:
        """加载世界存档"""
        try:
            if path is None or hasattr(path, "control"):
                path = self.app.current_save_path
            if not path:
                self.app.warn_dialog("提示", "请先通过侧边栏设置当前存档。")
                return

            # 显示加载状态
            self._world_label.value = "⏳ 正在加载存档..."
            self._world_label.color = THEME.mc_gold
            safe_update(self._world_label)
            self._world_load_generation += 1
            generation = self._world_load_generation
            self._invalidate_quick_backup_state()
            self._invalidate_stats_analysis_state()
            self._set_map_marker_busy(False)
            self.app.hide_progress()

            self._task_scope.cancel_all()
            self._task_scope.submit(
                "load_world",
                lambda token: self._load_world_worker(
                    str(path),
                    generation,
                    token,
                ),
                priority=TaskPriority.VISIBLE,
                feature="explorer",
                world_id=str(path),
                generation=generation,
            )
        except Exception as ex:
            self.app.handle_exception(ex, title="设置当前存档失败")

    def _load_world_worker(
        self,
        path: str,
        generation: int,
        context: OperationContext,
    ) -> None:
        """Load shell metadata first, then full session (progressive publish)."""
        try:
            context.report_progress(0, 3, "open_world")
            context.raise_if_cancelled()
            world = Path(path)
            repository = self.app.world_repository
            read_context: Optional[WorldReadContext] = None
            try:
                read_context = repository.open(world)
                context.raise_if_cancelled()
                self._post_world_ui(
                    context,
                    "shell",
                    lambda: self._apply_shell_metadata(
                        read_context.shell,
                        generation,
                    ),
                )
            except (OSError, ValueError, FileNotFoundError, TypeError):
                # Shell metadata is best-effort; full load still proceeds.
                pass
            context.report_progress(1, 3, "shell_ready")
            context.raise_if_cancelled()
            session = self._create_world_session(
                world,
                self.app.log,
                read_context=read_context,
            )
            context.report_progress(2, 3, "session_ready")
            context.raise_if_cancelled()
            self._post_world_ui(
                context,
                "result",
                lambda: self._apply_loaded_world(session, generation),
            )
            context.report_progress(3, 3, "delivered")
        except OperationCancelledError:
            return
        except Exception as exc:
            if context.is_cancelled:
                return
            self._post_world_ui(
                context,
                "error",
                lambda error=exc: self._show_world_load_error(
                    error,
                    generation,
                ),
            )

    def _post_world_ui(
        self,
        context: OperationContext,
        event: str,
        callback: Callable[[], None],
    ) -> None:
        """将世界加载投影交给统一 UI 通道并附带 generation 守卫。"""
        self.app.ui_delivery.post(
            UiDeliverySpec(
                task_id=context.task_id,
                operation=context.operation,
                feature=context.feature,
                world_id=context.world_id,
                generation=context.generation,
                event=event,
                metadata=context.metadata,
            ),
            callback,
            is_current=lambda: self._is_world_load_current(
                context.generation
            ),
        )

    def _apply_shell_metadata(
        self,
        shell: Any,
        generation: int,
    ) -> None:
        """首屏：在完整会话前显示世界名与区域规模提示。"""
        if not self._is_world_load_current(generation):
            return
        name = getattr(shell, "display_name", None) or "..."
        regions = int(getattr(shell, "overworld_region_count", 0) or 0)
        dims = int(getattr(shell, "dimension_hint_count", 0) or 0)
        self._world_label.value = (
            f"⏳ {name} · 区域 {regions} · 维度提示 {dims} · 加载中..."
        )
        self._world_label.color = THEME.mc_gold
        safe_update(self._world_label)

    def _create_world_session(
        self,
        path: Path,
        log: Any = None,
        *,
        read_context: Optional[WorldReadContext] = None,
    ) -> WorldSession:
        """Compose a session with application-scoped write safety ports."""
        if read_context is not None:
            return read_context.open_session(log=log or self.app.log)
        return self.app.world_repository.open_session(
            path,
            log=log or self.app.log,
        )

    def _apply_loaded_world(
        self,
        session: WorldSession,
        generation: int,
    ) -> None:
        if not self._is_world_load_current(generation):
            return
        try:
            self._populate_world(session)
        except Exception as exc:
            self.app.handle_exception(exc, title="更新存档界面失败")

    def _show_world_load_error(
        self,
        error: Exception,
        generation: int,
    ) -> None:
        if not self._is_world_load_current(generation):
            return
        if isinstance(error, FileNotFoundError):
            self._world_label.value = "存档无效"
            self._world_label.color = THEME.error
            title = "无效的存档"
            message = (
                "所选目录不是有效的 Minecraft 存档：\n\n"
                f"{error}\n\n请确保选择包含 level.dat 的存档根目录"
            )
        elif isinstance(error, RuntimeError):
            self._world_label.value = "NBT 解析失败"
            self._world_label.color = THEME.error
            title = "NBT 解析失败"
            message = (
                f"level.dat 文件损坏或格式不兼容：\n\n{error}\n\n"
                "可能原因：\n• 存档文件损坏\n"
                "• 不支持的 Minecraft 版本\n• 文件被其他程序占用"
            )
        else:
            self._world_label.value = "加载存档失败"
            self._world_label.color = THEME.warning
            title = "加载存档失败"
            message = f"{type(error).__name__}: {error}"
        safe_update(self._world_label)
        self.app.error_dialog(title, message)

    def dispose(self) -> None:
        """Release session-scoped background resources."""
        if self._disposed:
            return
        self._disposed = True
        self._world_load_generation += 1
        self._invalidate_quick_backup_state()
        self._invalidate_stats_analysis_state()
        self._map_controller.close()
        data_loader = getattr(self, "_data_loader", None)
        if data_loader is not None:
            data_loader.dispose()
        self._task_scope.close()
        if hasattr(self, "_entity_block_search_view"):
            self._entity_block_search_view.dispose()
        self._dispose_player_tab()
        self._dispose_region_tab()
        self._map_service.close()

    def _is_world_load_current(self, generation: int) -> bool:
        """Return whether a delayed world-load callback still owns the view."""
        return (
            not self._disposed
            and generation == self._world_load_generation
        )

    def _populate_world(self, session: WorldSession) -> None:
        """在 WorldSession 加载完成后填充 UI（可在后台线程调用）"""
        self.world_session = session
        self._world_label.value = f"当前存档: {session.world_path.name}"
        self._world_label.color = THEME.text_muted
        self._nbt_view_state = clear_nbt_target(self._nbt_view_state)
        self._nbt_stage_store.clear()
        self._update_nbt_target_options()
        self._update_nbt_stage_status()
        safe_update(self._world_label)

        # 更新存档信息面板
        world_info = session.get_world_info()
        dimensions = session.get_dimensions()
        self._map_controller.bind_world(session.world_path, dimensions)
        self._request_map_marker_load()
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
