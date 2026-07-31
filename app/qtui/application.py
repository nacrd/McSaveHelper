"""Qt 组合根：装配服务、壳层与视图（对应 Flet 版 ``app/application.py``）。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from app.adapters.file_dialogs import FileType
from app.bootstrap.services import AppServices, create_app_services
from app.models.save_store import CurrentSaveStore
from app.qtui.context import QtFeatureContext
from app.qtui.dialogs import QtFileDialogs, QtMessageDialogs
from app.qtui.registry import create_qt_registry
from app.qtui.shell import QtShell
from app.qtui.sidebar import QtSidebar
from app.qtui.theme import get_theme_manager
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
from app.qtui.view_manager import QtViewManager
from app.services.ui_delivery import UiDeliveryChannel
from app.core.save_context_manager import SaveContextManager
from app.services.region_map import RegionMapService

if TYPE_CHECKING:
    from app.services.backup_service import BackupService
    from app.services.cache_registry import CacheRegistry
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.item_service import ItemService
    from app.services.migration_service import MigrationService
    from app.services.save_repair_service import SaveRepairService
    from app.services.texture_service import TextureService
    from app.services.uuid_service import UUIDService
    from app.services.world_compare_service import WorldCompareService
    from app.services.world_repository import WorldRepository
    from app.services.world_stats_service import WorldStatsService
    from app.services.world_transaction import WorldTransactionService


class QtApplication(QMainWindow):
    """MCSaveHelper Qt 组合根。

    装配应用服务、主题、对话框、存档上下文、视图管理器与壳层。
    窗口关闭时释放视图、运行时与服务。
    """

    def __init__(
        self,
        services: Optional[AppServices] = None,
    ) -> None:
        """初始化应用。

        Args:
            services: 已装配的应用服务；缺省自动创建。
        """
        super().__init__()
        self.services = services or create_app_services()
        self.config = self.services.config
        self.i18n = self.services.i18n

        # ─── 主题 ─────────────────────────────────
        saved_theme = self.config.ui_settings.get("theme", "dark")
        try:
            get_theme_manager().set_mode(saved_theme)
        except ValueError:
            get_theme_manager().set_mode("dark")
        self._apply_theme_style()

        # ─── 对话框与文件选择器 ────────────────────
        self.message_dialogs = QtMessageDialogs(parent=self)
        self.file_dialogs = QtFileDialogs(parent=self)

        # ─── UI 投递通道 ───────────────────────────
        self.ui_delivery = UiDeliveryChannel(
            self._schedule_ui_callback,
            self.services.operation_metrics.record,
        )

        # ─── 存档上下文 ───────────────────────────
        self.current_save_store = CurrentSaveStore()
        self.current_save_store.subscribe_current(self._on_current_save_changed)
        self.current_save_store.subscribe_recent(self._on_recent_saves_changed)
        self.save_context_manager = SaveContextManager(
            config=self.config,
            store=self.current_save_store,
            pick_directory=lambda: self.pick_directory(),
            warn_dialog=self.warn_dialog,
            error_dialog=self.error_dialog,
            activate_save=self._activate_current_save,
            log=self.log,
        )

        # ─── 视图管理器与壳层 ──────────────────────
        self.registry = create_qt_registry()
        self._stack = QStackedWidget()
        self.feature_context = QtFeatureContext(self)
        self.view_manager = QtViewManager(
            registry=self.registry,
            stack=self._stack,
            context=self.feature_context,
            on_view_changed=self._on_view_changed,
        )
        self.sidebar = self._build_sidebar()
        self.shell = QtShell(
            translate=self.translate,
            sidebar=self.sidebar,
            view_stack=self._stack,
            on_view_action=self._on_view_action,
        )
        self._setup_window()

        # 壳层就绪后再加载持久化存档状态（回调需要侧边栏存在）。
        self.save_context_manager.initialize()

        # ─── 默认视图 ─────────────────────────────
        first_view_id = self.registry.features[0].view_id
        self.view_manager.switch_view(first_view_id)
        self.sidebar.select_tab(first_view_id)

    # ════════════════════════════════════════════
    #  壳层构建
    # ════════════════════════════════════════════

    def _setup_window(self) -> None:
        """设置窗口标题、尺寸与中央壳层。"""
        self.setWindowTitle("MCSaveHelper")
        self.setCentralWidget(self.shell)
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)

    def _build_sidebar(self) -> QtSidebar:
        tab_defs = self.registry.sidebar_definitions(self.translate)
        return QtSidebar(
            tabs=tab_defs,
            translate=self.translate,
            on_tab_select=self._on_tab_select,
            on_import_save=self._on_import_save,
            on_recent_save_select=self._on_recent_save_select,
            recent_saves=self._recent_saves(),
            current_save_path=self.current_save_path,
            on_pick_current_save=self._on_pick_current_save,
        )

    def _apply_theme_style(self) -> None:
        """把当前主题色板同步到应用 QSS（窗口创建前调用）。"""
        from app.qtui.theme import apply_theme

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, get_theme_manager().mode)

    @staticmethod
    def _schedule_ui_callback(callback: Callable[[], None]) -> bool:
        """把 UI 投递回调调度到主线程；总是接受。"""
        run_on_ui(callback)
        return True

    # ════════════════════════════════════════════
    #  侧边栏事件
    # ════════════════════════════════════════════

    def _on_tab_select(self, view_id: str) -> None:
        self.view_manager.switch_view(view_id)

    def _on_view_changed(self, view_id: str) -> None:
        self.sidebar.select_tab(view_id)
        self._refresh_top_actions(view_id)

    def _refresh_top_actions(self, view_id: str) -> None:
        actions = self.view_manager.get_top_actions(view_id)
        self.shell.set_view_actions(actions)

    def _on_view_action(self, action: QtViewAction) -> None:
        action.handler()

    def _on_import_save(self) -> None:
        self.save_context_manager.on_import_save()

    def _on_pick_current_save(self) -> None:
        self.save_context_manager.on_import_save()

    def _on_recent_save_select(self, path: str) -> None:
        self.save_context_manager.on_recent_save_select(path)

    def _on_current_save_changed(self, context: object) -> None:
        if hasattr(self, "sidebar"):
            self.sidebar.set_current_save(self.current_save_path)
        if context is None:
            if hasattr(self, "view_manager"):
                self.view_manager.notify_save_cleared()
            return
        if hasattr(self, "view_manager"):
            self.view_manager.notify_save_selected(str(getattr(context, "display_path", "")))

    def _on_recent_saves_changed(self, _recent: object) -> None:
        if hasattr(self, "sidebar"):
            self.sidebar.set_recent_saves(self._recent_saves())

    def _recent_saves(self) -> list[dict[str, Any]]:
        return [
            {"path": save.path, "name": save.name}
            for save in self.current_save_store.recent
        ]

    def _activate_current_save(self, path: str) -> None:
        del path
        # 首个迁移视图无存档绑定需求；资源浏览器迁移后在此刷新。

    # ════════════════════════════════════════════
    #  翻译 / 日志
    # ════════════════════════════════════════════

    def translate(self, key: str, default: str = "", **kwargs: Any) -> str:
        return self.i18n.translate(key, default, **kwargs)

    def log(self, msg: str, level: str = "INFO") -> None:
        from core.logger import LogLevel, logger

        log_level = LogLevel.from_string(level)
        logger.log(log_level, msg, module="QtApp")

    # ════════════════════════════════════════════
    #  对话框端口
    # ════════════════════════════════════════════

    def info_dialog(self, title: str, message: str) -> None:
        self.message_dialogs.info_dialog(title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        self.message_dialogs.warn_dialog(title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False,
    ) -> None:
        self.message_dialogs.error_dialog(title, message, exception, show_details)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True,
    ) -> None:
        self.message_dialogs.handle_exception(exception, title, log, show_dialog)

    # ─── 文件对话框端口 ───────────────────────────

    def pick_directory(self) -> Optional[str]:
        return self.file_dialogs.pick_directory("选择文件夹")

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.file_dialogs.pick_file(title, file_types or [])

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[list[str]]:
        return self.file_dialogs.pick_files(title, file_types or [])

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[list[FileType]] = None,
    ) -> Optional[str]:
        return self.file_dialogs.save_file(title, default_ext, file_types or [])

    # ─── 进度端口 ─────────────────────────────────

    def show_progress(self, task_name: str = "") -> None:
        self.shell.progress.show_progress(task_name)

    def hide_progress(self) -> None:
        self.shell.progress.hide_progress()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        self.shell.progress.update_progress_with_task(task_name, value)

    # ─── 其他端口 ─────────────────────────────────

    @property
    def current_save_path(self) -> Optional[str]:
        return self.save_context_manager.get_current_save_path()

    def create_region_map_service(self) -> RegionMapService:
        return RegionMapService(
            self.execution_runtime,
            cache_registry=self.services.cache_registry,
        )

    def update_uuid_mappings(self, mappings: dict[str, str]) -> None:
        self.config.custom_uuid_mappings = mappings
        self.config.save()

    @property
    def execution_runtime(self) -> "ExecutionRuntime":
        return self.services.execution_runtime

    @property
    def migration(self) -> "MigrationService":
        return self.services.migration

    @property
    def uuid(self) -> "UUIDService":
        return self.services.uuid

    @property
    def item(self) -> "ItemService":
        return self.services.item

    @property
    def texture(self) -> "TextureService":
        return self.services.texture

    @property
    def backup(self) -> "BackupService":
        return self.services.backup

    @property
    def save_repair(self) -> "SaveRepairService":
        return self.services.save_repair

    @property
    def world_compare(self) -> "WorldCompareService":
        return self.services.world_compare

    @property
    def world_transactions(self) -> "WorldTransactionService":
        return self.services.world_transactions

    @property
    def world_repository(self) -> "WorldRepository":
        return self.services.world_repository

    @property
    def world_stats(self) -> "WorldStatsService":
        return self.services.world_stats

    @property
    def cache_registry(self) -> "CacheRegistry":
        return self.services.cache_registry

    # ════════════════════════════════════════════
    #  生命周期
    # ════════════════════════════════════════════

    def closeEvent(self, event: QCloseEvent) -> None:
        """窗口关闭时按序释放资源。"""
        self._shutdown()
        super().closeEvent(event)

    def _shutdown(self) -> None:
        """释放视图、运行时、缓存与服务（幂等）。"""
        self.view_manager.dispose_all()
        self.services.execution_runtime.shutdown(wait=True, timeout=5.0)
        self.services.world_indexes.close()
        self.services.cache_registry.close()
        self.texture.close()
        self.ui_delivery.close()
