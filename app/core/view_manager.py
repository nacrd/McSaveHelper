"""View Manager - 视图管理

负责视图的创建、切换、缓存和顶部操作按钮管理。
"""
from typing import TYPE_CHECKING, Dict, List, Callable
from dataclasses import dataclass
import traceback
import flet as ft

from app.ui.theme import THEME
from app.ui.components.buttons import btn_primary, btn_danger
from core.logger import logger

if TYPE_CHECKING:
    from app.application import Application


@dataclass(frozen=True)
class TopAction:
    """页面级顶部操作按钮描述符

    Attributes:
        label: 按钮标签
        handler: 点击处理函数
        style: 按钮样式（"primary" 或 "danger"）
    """
    label: str
    handler: Callable[[ft.ControlEvent], None]
    style: str = "primary"


class ViewManager:
    """视图管理器

    职责：
    - 视图创建和缓存
    - 视图切换
    - 顶部操作按钮管理
    - 视图错误处理
    """

    def __init__(self, app: "Application") -> None:
        """初始化视图管理器

        Args:
            app: 应用实例
        """
        self.app = app
        self.page = app.page
        self.views: Dict[str, ft.Control] = {}

    def switch_view(self, view_id: str) -> None:
        """切换到指定视图

        Args:
            view_id: 视图ID
        """
        try:
            # 创建或获取缓存的视图
            if view_id not in self.views:
                self.views[view_id] = self._create_view(view_id)

            current_view = self.views[view_id]
            self.app._content.content = current_view
            self._update_top_actions(view_id, current_view)

            # 如果有当前存档，通知视图
            if self.app._current_save_path and hasattr(current_view, 'on_save_selected'):
                try:
                    current_view.on_save_selected(self.app._current_save_path)
                except Exception as ex:
                    self.app.log(f"同步当前存档失败: {ex}", "ERROR")

            self.page.update()
        except Exception as e:
            traceback.print_exc()
            self.app.log(f"加载视图 '{view_id}' 失败: {e}", "ERROR")
            self._handle_view_error(view_id, e)

    def _create_view(self, view_id: str) -> ft.Control:
        """创建指定视图

        Args:
            view_id: 视图ID

        Returns:
            ft.Control: 视图控件
        """
        # 延迟导入视图模块，避免循环依赖
        from app.ui.views.migrator import MigratorView
        from app.ui.views.explorer import ExplorerView
        from app.ui.views.mappings import MappingsView
        from app.ui.views.settings import SettingsView
        from app.ui.views.compare import CompareView
        from app.ui.views.server_properties import ServerPropertiesView
        from app.ui.views.save_repair import SaveRepairView
        from app.ui.views.map_export import MapExportView

        view_map = {
            "migrator": MigratorView,
            "explorer": ExplorerView,
            "save_repair": SaveRepairView,
            "map_export": MapExportView,
            "compare": CompareView,
            "server_properties": ServerPropertiesView,
            "mappings": MappingsView,
            "settings": SettingsView,
        }

        view_class = view_map.get(view_id)
        if view_class:
            return view_class(self.app)

        return ft.Container()

    def _update_top_actions(self, view_id: str, current_view: ft.Control) -> None:
        """更新顶部操作按钮

        Args:
            view_id: 视图ID
            current_view: 当前视图控件
        """
        actions = self._get_top_actions(view_id, current_view)
        self.app._top_actions.controls.clear()

        for action in actions:
            width = max(86, min(140, len(action.label) * 14 + 28))
            builder = btn_danger if action.style == "danger" else btn_primary
            self.app._top_actions.controls.append(
                builder(action.label, on_click=action.handler, width=width, height=38)
            )

        self.app._top_actions.visible = bool(actions)

    def _get_top_actions(
        self,
        view_id: str,
        current_view: ft.Control
    ) -> List[TopAction]:
        """获取视图的顶部操作按钮列表

        Args:
            view_id: 视图ID
            current_view: 当前视图控件

        Returns:
            List[TopAction]: 操作按钮列表
        """
        _t = self.app._t
        if view_id == "explorer":
            return [
                TopAction(
                    _t("top_bar.start_stats", "开始统计"),
                    lambda e: current_view._analyze_world_stats(e)
                ),
                TopAction(
                    _t("top_bar.open_search", "打开搜索"),
                    lambda e: current_view._start_entity_block_search(e)
                ),
                TopAction(
                    _t("top_bar.refresh_map", "刷新地图"),
                    lambda e: current_view._refresh_map()
                ),
                TopAction(
                    _t("top_bar.stage_player", "暂存玩家"),
                    lambda e: current_view._stage_player_edit_form(e)
                ),
                TopAction(
                    _t("top_bar.commit_changes", "提交变更"),
                    lambda e: current_view._commit_nbt_changes(e)
                ),
                TopAction(
                    _t("top_bar.discard_changes", "丢弃暂存"),
                    lambda e: current_view._discard_nbt_changes(e),
                    "danger"
                ),
            ]

        action_map: Dict[str, TopAction] = {
            "migrator": TopAction(
                _t("top_bar.start_conversion", "开始转换"),
                lambda e: self.app.start()
            ),
            "save_repair": TopAction(
                _t("top_bar.detect_save", "检测存档"),
                lambda e: current_view._start_detect(e)
            ),
            "map_export": TopAction(
                _t("top_bar.start_export", "开始导出"),
                lambda e: current_view._start_export(e)
            ),
            "compare": TopAction(
                _t("top_bar.start_compare", "开始对比"),
                lambda e: current_view._compare(e)
            ),
            "mappings": TopAction(
                _t("top_bar.import_lang", "导入语言文件"),
                lambda e: current_view._import_lang(e)
            ),
            "server_properties": TopAction(
                _t("top_bar.read_config", "读取配置"),
                lambda e: current_view._load(e)
            ),
        }

        action = action_map.get(view_id)
        return [action] if action else []

    def _handle_view_error(self, view_id: str, error: Exception) -> None:
        """处理视图加载错误

        Args:
            view_id: 视图ID
            error: 异常对象
        """
        try:
            self.app._content.content = self.app.dialog_manager.build_error_placeholder(
                view_id, error
            )
            self.page.update()
        except Exception:
            self._show_simple_error(view_id, error)

    def _show_simple_error(self, view_id: str, error: Exception) -> None:
        """显示简单错误信息

        Args:
            view_id: 视图ID
            error: 异常对象
        """
        try:
            self.app._content.content = ft.Container(
                content=ft.Text(
                    f"加载页面 '{view_id}' 时出错: {error}",
                    color=THEME.error,
                    size=14,
                ),
                padding=40,
            )
            self.page.update()
        except Exception:
            pass

    def notify_current_view_save_selected(self, path: str) -> None:
        """通知当前视图存档已选中

        Args:
            path: 存档路径
        """
        current_view = self.views.get(
            self.app._sidebar.selected_id if hasattr(self.app, '_sidebar') else None
        )
        if current_view and hasattr(current_view, 'on_save_selected'):
            try:
                current_view.on_save_selected(path)
            except Exception as ex:
                self.app.log(f"通知视图失败: {ex}", "ERROR")
