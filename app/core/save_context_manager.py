"""Save Context Manager - 当前存档上下文管理

负责当前存档的设置、获取、最近存档管理和存档选择回调。
"""
from typing import TYPE_CHECKING, Optional, List, Dict
import flet as ft

from app.models.save_context import CurrentSaveContext
from core.logger import logger

if TYPE_CHECKING:
    from app.application import Application


class SaveContextManager:
    """当前存档上下文管理器

    职责：
    - 设置和获取当前存档
    - 最近存档列表管理
    - 存档选择回调处理
    - 存档验证
    """

    def __init__(self, app: "Application") -> None:
        """初始化存档上下文管理器

        Args:
            app: 应用实例
        """
        self.app = app
        self.page = app.page
        self._current_save_context: Optional[CurrentSaveContext] = None
        self._current_save_path: Optional[str] = None
        self._recent_saves: List[Dict[str, str]] = []

    def initialize(self) -> None:
        """初始化存档上下文管理器"""
        self._recent_saves = self._load_recent_saves()

    def get_current_save_context(self) -> Optional[CurrentSaveContext]:
        """获取当前存档上下文

        Returns:
            Optional[CurrentSaveContext]: 当前存档上下文
        """
        return self._current_save_context

    def get_current_save_path(self) -> Optional[str]:
        """获取当前存档路径

        Returns:
            Optional[str]: 当前存档路径
        """
        return self._current_save_path

    def get_recent_saves(self) -> List[Dict[str, str]]:
        """获取最近存档列表

        Returns:
            List[Dict[str, str]]: 最近存档列表
        """
        return self._recent_saves

    def set_current_save_context(self, context: CurrentSaveContext) -> None:
        """设置当前存档上下文

        Args:
            context: 存档上下文
        """
        self._current_save_context = context
        self._current_save_path = context.display_path

        # 更新侧边栏显示
        if hasattr(self.app, '_sidebar'):
            self.app._sidebar.set_current_save_name(
                context.name,
                context.display_path
            )

        # 记录到最近存档
        self._remember_recent_save(context)

        # 激活存档浏览器
        self._activate_explorer_with_current_save(context.display_path)

        # 显示通知
        if hasattr(self.app, "gui_optimizer") and self.app.gui_optimizer.notification_manager:
            self.app.gui_optimizer.notification_manager.show_success(
                f"当前存档已设置为 {context.name}，相关功能将自动使用该存档"
            )

    def on_import_save(self) -> None:
        """侧边栏设置当前存档按钮回调"""
        try:
            path = self.app.dialog_manager.pick_directory()
            if not path:
                return

            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self.app.dialog_manager.warn_dialog(
                    "提示",
                    "这不是有效存档目录，请选择包含 level.dat 的文件夹。"
                )
                return

            self.set_current_save_context(context)
        except Exception as ex:
            self.app.dialog_manager.error_dialog("错误", f"设置当前存档失败: {ex}")

    def on_recent_save_select(self, path: str) -> None:
        """最近存档选择回调

        Args:
            path: 存档路径
        """
        try:
            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self.app.dialog_manager.warn_dialog(
                    "提示",
                    "该最近存档已失效，目录中未找到 level.dat。"
                )
                # 从最近列表中移除
                self._recent_saves = [
                    s for s in self._recent_saves
                    if s.get("path") != path
                ]
                if hasattr(self.app, '_sidebar'):
                    self.app._sidebar.set_recent_saves(self._recent_saves)
                self._save_recent_saves()
                return

            self.set_current_save_context(context)
        except Exception as ex:
            self.app.dialog_manager.error_dialog("错误", f"设置当前存档失败: {ex}")

    def _activate_explorer_with_current_save(self, path: str) -> None:
        """激活存档浏览器并设置当前存档

        Args:
            path: 存档路径
        """
        try:
            # 确保 explorer 视图已创建
            if "explorer" not in self.app.views:
                self.app.views["explorer"] = self.app.view_manager._create_view("explorer")

            explorer_view = self.app.views["explorer"]

            # 通知视图存档已选中
            if hasattr(explorer_view, "on_save_selected"):
                explorer_view.on_save_selected(path)

            # 切换到 explorer 视图
            if hasattr(self.app, '_sidebar'):
                if self.app._sidebar.selected_id != "explorer":
                    self.app._sidebar.select_tab("explorer")
                else:
                    self.app._content.content = explorer_view
                    self.app.view_manager._update_top_actions("explorer", explorer_view)
                    self.page.update()
        except Exception as ex:
            self.app.log(f"激活存档浏览器失败: {ex}", "ERROR")

    def _load_recent_saves(self) -> List[Dict[str, str]]:
        """从配置加载最近存档

        Returns:
            List[Dict[str, str]]: 最近存档列表
        """
        try:
            saves = self.app.config.config.get("recent_saves", [])
            if isinstance(saves, list):
                return [
                    s for s in saves
                    if isinstance(s, dict) and s.get("path")
                ][:5]
        except Exception:
            pass
        return []

    def _save_recent_saves(self) -> None:
        """保存最近存档到配置"""
        try:
            self.app.config.config["recent_saves"] = self._recent_saves[:5]
            self.app.config.save()
        except Exception as ex:
            self.app.log(f"保存最近存档失败: {ex}", "ERROR")

    def _remember_recent_save(self, context: CurrentSaveContext) -> None:
        """记录到最近存档

        Args:
            context: 存档上下文
        """
        save = {"path": context.display_path, "name": context.name}

        # 移除已存在的相同路径
        self._recent_saves = [
            s for s in self._recent_saves
            if s.get("path") != context.display_path
        ]

        # 插入到首位
        self._recent_saves.insert(0, save)

        # 保持最多5个
        self._recent_saves = self._recent_saves[:5]

        # 更新侧边栏
        if hasattr(self.app, '_sidebar'):
            self.app._sidebar.set_recent_saves(self._recent_saves)

        # 保存到配置
        self._save_recent_saves()
