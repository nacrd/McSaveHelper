"""Qt 组合根：装配服务、壳层与视图（对应 Flet 版 ``app/application.py``）。"""
from __future__ import annotations

from contextlib import ExitStack
import os
from typing import TYPE_CHECKING, Any, Callable, Optional

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from app.adapters.file_dialogs import FileType
from app.bootstrap.services import AppServices, create_app_services
from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore
from app.qtui.context import QtFeatureContext, QtMigrationCommands
from app.qtui.dialogs import QtFileDialogs, QtMessageDialogs
from app.qtui.log_panel import QtLogPanel, install_qt_log_handler
from app.qtui.log_alerts import QtAlertController
from app.qtui.migration_coordinator import QtMigrationCoordinator
from app.qtui.registry import create_qt_registry
from app.qtui.shell import QtShell
from app.qtui.sidebar import QtSidebar
from app.qtui.theme import get_theme_manager
from app.qtui.utils import run_on_ui
from app.qtui.view_actions import QtViewAction
from app.qtui.view_manager import QtViewManager
from app.qtui.registry import QtNavigationDescriptor
from app.services.ui_delivery import UiDeliveryChannel
from app.core.save_context_manager import SaveContextManager
from app.services.item.language_loader import LanguageImportResult
from app.services.region_map import RegionMapService
from core.logger import LogHandler, LogLevel, logger, setup_default_logging
from core.logging.storage import DailyJsonlHandler
from app.services.log_alert_service import SmtpEmailNotifier, SmtpSettings

if TYPE_CHECKING:
    from app.models.config import ApplicationSettings
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
        settings = self.config.get_settings()

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
        self._active_navigation_id: Optional[str] = None
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
            on_pick_world=self._on_pick_current_save,
            on_recent_world=self._on_recent_save_select,
            on_quick_backup=self._on_quick_backup,
        )
        self._setup_window()
        self._setup_logging(settings.show_log_panel)
        self._alert_controller: Optional[QtAlertController] = None
        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._alert_message_boxes: list[QMessageBox] = []
        self._setup_alerts()
        self._migration_coordinator = QtMigrationCoordinator(self)
        self._shutdown_started = False
        self._sidebar_mode = settings.sidebar_mode
        self._apply_sidebar_mode()
        self.services.performance_monitoring.configure(
            settings.enable_performance_monitor,
            float(settings.performance_print_interval),
        )

        # 壳层就绪后再加载持久化存档状态（回调需要侧边栏存在）。
        self.save_context_manager.initialize()

        # ─── 默认视图 ─────────────────────────────
        self.shell.set_recent_saves(self._recent_saves())
        first_navigation_id = self.registry.navigation[0].navigation_id
        self.navigate_to(first_navigation_id)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.aboutToQuit.connect(self._shutdown)

    # ════════════════════════════════════════════
    #  壳层构建
    # ════════════════════════════════════════════

    def _setup_window(self) -> None:
        """设置窗口标题、尺寸与中央壳层。"""
        self.setWindowTitle("MCSaveHelper")
        self.setCentralWidget(self.shell)
        self.resize(1180, 760)
        self.setMinimumSize(860, 560)

    def _setup_logging(self, show_panel: bool) -> None:
        """装配文件/控制台日志与 Qt 日志 dock。"""
        setup_default_logging(
            enable_console=True,
            enable_file=True,
            enable_ui=False,
            level=LogLevel.DEBUG,
            capture_print=True,
        )
        self._qt_settings = QSettings("MCSaveHelper", "MCSaveHelper")
        self.log_panel = QtLogPanel(
            self.translate("log_panel.title", "日志"),
            self,
            query_service=self.services.log_query,
            export_service=self.services.log_export,
            alert_service=self.services.log_alerts,
            settings=self._qt_settings,
            clear_logs=self._clear_log_archives,
            translate=self.translate,
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_panel)
        self.log_panel.setVisible(show_panel)
        self._qt_log_handler: LogHandler = install_qt_log_handler(self.log_panel)
        for handler in logger.handlers:
            if isinstance(handler, DailyJsonlHandler):
                handler.set_status_callback(self.log_panel.show_storage_warning)
        logger.info("MCSaveHelper Qt 应用启动", module="QtApp")
        self.log_panel.reload()
        dock_state = self._qt_settings.value("log_viewer/main_window_state")
        if dock_state is not None:
            self.restoreState(dock_state)

    def _clear_log_archives(self) -> int:
        """安全清理当前日志管线管理的所有 JSONL 文件。"""
        logger.flush()
        deleted = 0
        for handler in logger.handlers:
            if isinstance(handler, DailyJsonlHandler):
                deleted += handler.clear_archives()
        return deleted

    def _setup_alerts(self) -> None:
        """装配本地告警调度和可选系统/SMTP通知端口。"""
        alert_service = self.services.log_alerts
        if alert_service is None:
            return
        email_notify = None
        smtp_host = os.environ.get("MCSAVEHELPER_SMTP_HOST", "")
        if smtp_host:
            try:
                smtp_port = int(os.environ.get("MCSAVEHELPER_SMTP_PORT", "587"))
            except ValueError:
                smtp_port = 587
                logger.warning("SMTP 端口无效，已使用默认端口", module="LogAlert")
            email_notify = SmtpEmailNotifier(SmtpSettings(
                host=smtp_host,
                port=smtp_port,
                username=os.environ.get("MCSAVEHELPER_SMTP_USER", ""),
                sender=os.environ.get("MCSAVEHELPER_SMTP_FROM", ""),
            ))
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray_icon = QSystemTrayIcon(self.windowIcon(), self)
            tray_icon.show()
            self._tray_icon = tray_icon
        self._alert_controller = QtAlertController(
            alert_service,
            self._show_log_alert,
            email_notify=email_notify,
            parent=self,
        )
        self._alert_controller.check_failed.connect(
            lambda message: logger.warning(message, module="LogAlert")
        )
        self._alert_controller.start()

    def _show_log_alert(self, event: object) -> None:
        """在主线程显示系统告警；无托盘时回退非模态消息框。"""
        rule_name = getattr(event, "rule_name", self.tr("日志告警"))
        count = getattr(event, "count", 0)
        level = getattr(event, "level", "ERROR")
        title = self.translate("log_alerts.alert_title", self.tr("日志告警"))
        message = self.translate(
            "log_alerts.alert_message",
            self.tr("规则 {rule}：{level} 级别在窗口内出现 {count} 次"),
            rule=str(rule_name),
            level=str(level),
            count=str(count),
        )
        if self._tray_icon is not None:
            self._tray_icon.showMessage(title, message)
        else:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle(title)
            box.setText(message)
            box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._alert_message_boxes.append(box)
            box.finished.connect(self._remove_alert_message_box)
            box.show()

    def _remove_alert_message_box(self, result: int) -> None:
        """Drop a closed non-modal alert box from the ownership list."""
        del result
        self._alert_message_boxes[:] = [
            box for box in self._alert_message_boxes if not box.isVisible()
        ]

    def create_settings_view(self) -> QWidget:
        """构建设置视图（显式注入应用端口）。"""
        from app.qtui.views.settings import SettingsView, SettingsViewDependencies

        return SettingsView(SettingsViewDependencies(
            load_settings=self.config.get_settings,
            save_settings=self.config.update_settings,
            reset_settings=self._reset_settings,
            translate=self.translate,
            apply_theme=self._apply_theme,
            apply_language=self._apply_language,
            set_sidebar_mode=self._set_sidebar_mode,
            set_log_panel_visible=self._set_log_panel_visible,
            configure_performance_monitor=self._configure_performance_monitor,
            set_performance_interval=self._set_performance_interval,
            info_dialog=self.info_dialog,
            error_dialog=self.error_dialog,
            pick_directory=self.pick_directory,
            save_file=self.save_file,
            cache_snapshot=self.services.cache_registry.stats,
            clear_caches=self._clear_application_caches,
            cache_path=self._map_cache_path,
            execution_runtime=self.services.execution_runtime,
            runtime_snapshot=self.services.execution_runtime.snapshot,
            ui_delivery_summary=self.services.operation_metrics.ui_delivery_summary,
        ))

    def _reset_settings(self) -> "ApplicationSettings":
        """重置持久化设置并返回结果快照。"""
        self.config.reset_config()
        return self.config.get_settings()

    def _apply_theme(self, theme: str) -> None:
        """应用主题模式（QSS + 调色板）。"""
        from app.qtui.theme import apply_theme

        get_theme_manager().set_mode(theme)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        self.sidebar.refresh_theme()
        self.view_manager.refresh_theme()

    def _apply_language(self, language: str) -> None:
        """应用语言选择。"""
        self.i18n.set_language(language)

    def _set_sidebar_mode(self, mode: str) -> None:
        """应用固定展开、固定收窄或随窗口宽度自动切换。"""
        self._sidebar_mode = mode
        self._apply_sidebar_mode()

    def _apply_sidebar_mode(self) -> None:
        mode = getattr(self, "_sidebar_mode", "auto")
        collapsed = mode == "collapsed" or (
            mode == "auto" and self.width() < 1000
        )
        if collapsed == self.sidebar.is_collapsed:
            return
        self.sidebar.set_collapsed(collapsed)

    def _set_log_panel_visible(self, visible: bool) -> None:
        """显示或隐藏 Qt 日志 dock。"""
        self.log_panel.setVisible(visible)

    def _configure_performance_monitor(self, enabled: bool, interval: float) -> None:
        """启停应用级进程资源监控。"""
        self.services.performance_monitoring.configure(enabled, interval)

    def _set_performance_interval(self, seconds: float) -> None:
        """更新性能摘要日志打印间隔。"""
        self.services.performance_monitoring.set_print_interval(seconds)

    def _clear_application_caches(self) -> dict[str, int]:
        """清空内存与持久化瓦片缓存。"""
        from core.mca.tile_cache import clear_all_caches

        self.services.cache_registry.clear_all()
        result = clear_all_caches()
        return {
            "deleted_files": int(result.get("deleted_files", 0) or 0),
            "freed_bytes": int(result.get("freed_bytes", 0) or 0),
            "memory_chunks_cleared": int(
                result.get("memory_chunks_cleared", 0) or 0
            ),
        }

    @staticmethod
    def _map_cache_path() -> str:
        """返回持久化地图缓存路径。"""
        from core.mca.tile_cache import cache_dir

        return str(cache_dir())

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

    def navigate_to(self, navigation_id: str) -> None:
        """切换到导航入口，并在 Explorer 中打开指定工作区。

        Args:
            navigation_id: 注册表中的导航入口 id。

        Raises:
            KeyError: 导航入口不存在。
        """
        navigation = self.registry.get_navigation(navigation_id)
        if navigation is None:
            raise KeyError(f"未注册的 Qt 导航入口: {navigation_id}")
        was_created = self.view_manager.get_view(navigation.view_id) is not None
        self._active_navigation_id = navigation_id
        self.view_manager.switch_view(navigation.view_id)
        if not was_created:
            self._notify_new_view_of_current_save(navigation.view_id)
        self._select_navigation_workspace(navigation)
        self.sidebar.select_tab(navigation_id)

    def _on_tab_select(self, navigation_id: str) -> None:
        self.navigate_to(navigation_id)

    def _on_view_changed(self, view_id: str) -> None:
        navigation = self.registry.get_navigation(self._active_navigation_id or "")
        if navigation is None or navigation.view_id != view_id:
            navigation = self.registry.default_navigation_for_view(view_id)
            self._active_navigation_id = (
                navigation.navigation_id if navigation is not None else None
            )
        if navigation is not None:
            self.sidebar.select_tab(navigation.navigation_id)
            self._select_navigation_workspace(navigation)
        self._refresh_top_actions(view_id)

    def _select_navigation_workspace(
        self,
        navigation: QtNavigationDescriptor,
    ) -> None:
        """调用页面公开的工作区选择端口。"""
        if not navigation.workspace_id:
            return
        view = self.view_manager.get_view(navigation.view_id)
        selector = getattr(view, "select_workspace", None)
        if callable(selector):
            selector(navigation.workspace_id)

    def _notify_new_view_of_current_save(self, view_id: str) -> None:
        """为惰性创建的页面补发当前世界上下文。"""
        path = self.current_save_path
        if not path:
            return
        view = self.view_manager.get_view(view_id)
        handler = getattr(view, "on_save_selected", None)
        if callable(handler):
            handler(path)

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

    def _on_quick_backup(self) -> None:
        """从固定世界上下文栏直接启动快速备份。"""
        if not self.current_save_path:
            self._on_pick_current_save()
            return
        self.navigate_to("backup_center")
        view = self.view_manager.get_view("backup_center")
        start = getattr(view, "start_quick_backup", None)
        if callable(start):
            start()

    def _on_current_save_changed(
        self,
        context: Optional[CurrentSaveContext],
    ) -> None:
        if hasattr(self, "sidebar"):
            self.sidebar.set_current_save(self.current_save_path)
        if hasattr(self, "shell"):
            self.shell.set_current_save(
                self.current_save_path,
                status="ready" if context is not None else "required",
            )
        if context is None:
            if hasattr(self, "view_manager"):
                self.view_manager.notify_save_cleared()
            return
        if hasattr(self, "view_manager"):
            self.view_manager.notify_save_selected(context.display_path)
        self.services.auto_language_import.schedule(
            context,
            self._on_auto_language_imported,
        )

    def _on_auto_language_imported(self, result: LanguageImportResult) -> None:
        message = self.translate(
            "settings.auto_import_mc_lang_ok",
            "已自动导入 {count} 个 Minecraft 名称（{locale}）",
            count=result.count,
            locale=result.locale,
        )
        run_on_ui(self.shell.show_status_message, message)

    def _on_recent_saves_changed(self, _recent: object) -> None:
        if hasattr(self, "sidebar"):
            self.sidebar.set_recent_saves(self._recent_saves())
        if hasattr(self, "shell"):
            self.shell.set_recent_saves(self._recent_saves())

    def set_world_context_status(self, status: str, detail: str = "") -> None:
        """由页面报告世界加载或校验状态。"""
        if hasattr(self, "shell"):
            self.shell.set_world_status(status, detail)

    def set_navigation_badge(self, navigation_id: str, count: int) -> None:
        """更新侧栏导航待办数量。"""
        if hasattr(self, "sidebar"):
            self.sidebar.set_badge(navigation_id, count)

    def _recent_saves(self) -> list[dict[str, Any]]:
        return [
            {"path": save.path, "name": save.name}
            for save in self.current_save_store.recent
        ]

    def _activate_current_save(self, path: str) -> None:
        self.config.migration.src_path = path

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

    @property
    def migration_commands(self) -> "QtMigrationCommands":
        """返回迁移页面可用的应用级命令。"""
        return self._migration_coordinator.commands

    def get_migrator_view(self) -> Optional[QWidget]:
        """返回已创建的迁移视图。"""
        return self.view_manager.get_view("migrator")

    def set_migration_start_enabled(self, enabled: bool) -> None:
        """同步迁移页面和当前壳层的开始命令状态。"""
        view = self.get_migrator_view()
        setter = getattr(view, "set_start_enabled", None)
        if callable(setter):
            setter(enabled)
        label = self.translate("top_bar.start_conversion", "开始转换")
        self.shell.set_action_enabled(label, enabled)

    def update_migration_progress(self, value: float) -> None:
        """更新状态栏中的迁移进度。"""
        self.shell.progress.update_progress(value)

    def set_migration_progress_label(self, label: str) -> None:
        """更新状态栏中的迁移任务说明。"""
        self.shell.progress.set_progress_label(label)

    def set_migration_progress_value(self, value: float) -> None:
        """设置状态栏迁移进度值。"""
        self.shell.progress.update_progress(value)

    @staticmethod
    def post_ui(callback: Callable[[], None]) -> None:
        """把迁移控制器回调投递到 Qt 主线程。"""
        run_on_ui(callback)

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

    def resizeEvent(self, event: QResizeEvent) -> None:
        """自动侧边栏模式随窗口宽度变化。"""
        if hasattr(self, "sidebar") and getattr(self, "_sidebar_mode", "") == "auto":
            self._apply_sidebar_mode()
        super().resizeEvent(event)

    def _shutdown(self) -> None:
        """释放视图、运行时、缓存与服务（幂等）。"""
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._qt_settings.setValue("log_viewer/main_window_state", self.saveState())
        self._qt_settings.sync()
        logger.remove_handler(self._qt_log_handler)
        self.log_panel.dispose()
        with ExitStack() as cleanup:
            if self._alert_controller is not None:
                cleanup.callback(self._alert_controller.dispose)
            cleanup.callback(logger.shutdown)
            cleanup.callback(self.ui_delivery.close)
            cleanup.callback(self.texture.close)
            cleanup.callback(self.services.cache_registry.close)
            cleanup.callback(self.services.world_indexes.close)
            cleanup.callback(
                self.services.execution_runtime.shutdown,
                wait=True,
                timeout=5.0,
            )
            cleanup.callback(self.services.performance_monitoring.close)
            cleanup.callback(self.services.auto_language_import.close)
            cleanup.callback(self._migration_coordinator.close)
            cleanup.callback(self.view_manager.dispose_all)
