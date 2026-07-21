"""Application Core (Refactored) —— 应用主协调器

使用管理器模式重构的应用核心，协调各个管理器完成应用功能。

管理器职责分配：
- WindowManager: 窗口生命周期管理
- DialogManager: 对话框管理
- ViewManager: 视图管理
- ProgressManager: 进度管理
- GUIOptimizer: GUI优化功能集成
- SaveContextManager: 当前存档上下文管理
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, List, Dict
import flet as ft

from core.logger import LogLevel, logger, setup_default_logging

from app.bootstrap.services import AppServices, create_app_services
from app.adapters.file_dialogs import FileType, TkFileDialogs
from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore, RecentSave
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    OperationHandle,
    RuntimeClosedError,
    TaskPriority,
    TaskQueueFullError,
)
from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)

from app.ui.theme import THEME, get_theme_manager
from app.ui.utils import run_on_ui
from app.ui.view_catalog import create_default_view_catalog
from app.ui.application_shell import (
    ApplicationShellDependencies,
    build_application_shell,
)

# 导入管理器
from app.core.window_manager import (
    ResponsiveShellHost,
    WindowManager,
    WindowManagerDependencies,
)
from app.core.dialog_manager import DialogManager, DialogManagerDependencies
from app.core.view_manager import (
    ViewHost,
    ViewManager,
    ViewManagerDependencies,
)
from app.core.progress_manager import ProgressManager
from app.core.gui_optimizer import GUIOptimizer, GUIOptimizerDependencies
from app.core.save_context_manager import SaveContextManager

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.services.i18n_service import I18nService
    from app.services.execution_runtime import ExecutionRuntime
    from app.services.item_service import ItemService
    from app.services.migration_service import MigrationService
    from app.services.region_map_service import RegionMapService
    from app.services.texture_service import TextureService
    from app.services.uuid_service import UUIDService


class Application:
    """MCSaveHelper 应用核心（重构版）

    使用管理器模式协调各个功能模块。
    """

    def __init__(
        self,
        page: ft.Page,
        services: Optional[AppServices] = None,
    ) -> None:
        """初始化应用

        Args:
            page: Flet 页面对象
        """
        self.page: ft.Page = page
        self.services = services or create_app_services()
        # 自动语言导入：同路径去重 + generation 丢弃过期后台结果
        self._auto_lang_import_path: Optional[str] = None
        self._auto_lang_import_generation: int = 0
        self._auto_lang_import_lock = threading.Lock()
        self._auto_lang_import_task: Optional[OperationHandle[None]] = None

        # 全局异常兜底
        page.on_error = self._on_page_error

        # ─── 初始化主题 ─────────────────────────────
        self._init_theme()

        # ─── 初始化管理器 ───────────────────────────
        self._init_managers()

        # ─── 初始化 GUI 优化模块 ────────────────────
        self.gui_optimizer.initialize()

        # ─── 初始化控制器 ───────────────────────────
        self.migration_controller = MigrationController(
            MigrationControllerDependencies(
                config=self.config,
                migration=self.migration,
                translate=self._t,
                warn_dialog=self.warn_dialog,
                error_dialog=self.error_dialog,
                handle_exception=self.handle_exception,
                show_success=self._show_success,
                set_start_enabled=self.set_start_button_enabled,
                update_page=self.page.update,
                log=self.log,
                log_header=self.log_header,
                update_progress=self.update_progress,
                set_progress_label=self.set_progress_label,
                set_progress_value=self.set_progress_value,
                start_worker=self._start_migration_worker,
            )
        )

        # ─── 同步配置到迁移参数 ─────────────────────
        self._sync_config_to_migration()

        # ─── 初始化存档上下文（在构建 UI 之前）──────
        self.save_context_manager.initialize()

        # ─── 构建 UI ────────────────────────────────
        self._build_ui()

        # ─── 初始化日志 ─────────────────────────────
        self._init_logging()

        # ─── 切换到默认视图 ─────────────────────────
        self.view_manager.switch_view("explorer")
        page.update()

    # ════════════════════════════════════════════
    #  初始化
    # ════════════════════════════════════════════

    def _init_theme(self) -> None:
        """从配置初始化主题模式"""
        try:
            saved_theme = self.config.ui_settings.get("theme", "dark")
            manager = get_theme_manager()
            manager.set_mode(saved_theme)
        except Exception:
            # Default dark theme when config/theme bootstrap fails.
            pass

    def _init_managers(self) -> None:
        """初始化所有管理器"""
        # 文件对话框适配器（Tk 工作线程，关闭时需显式销毁）
        self._file_dialogs = TkFileDialogs()

        # 窗口管理器
        self.window_manager = WindowManager(WindowManagerDependencies(
            page=self.page,
            translate=self._t,
            apply_responsive_layout=(
                lambda layout: self.view_manager.apply_responsive_layout(layout)
            ),
            get_sidebar_mode=(
                lambda: self.config.get_settings().sidebar_mode
            ),
            stop_gui_optimizer=lambda: self.gui_optimizer.stop(),
            dispose_views=lambda: self.view_manager.dispose(),
            dispose_file_dialogs=self._file_dialogs.close,
            shutdown_execution_runtime=self.execution_runtime.shutdown,
            close_world_indexes=self.services.world_indexes.close,
        ))
        self.window_manager.setup_window()

        # 对话框管理器
        self.dialog_manager = DialogManager(DialogManagerDependencies(
            page=self.page,
            translate=self._t,
            switch_view=lambda view_id: self.view_manager.switch_view(view_id),
            remove_view=lambda view_id: self.view_manager.remove_view(view_id),
            copy_to_clipboard=self._copy_to_clipboard,
            show_snackbar=self._show_snackbar,
            file_dialogs=self._file_dialogs,
        ))

        # 视图管理器
        view_catalog = create_default_view_catalog(
            settings_factory=lambda app: app.create_settings_view(),
        )
        self.view_manager = ViewManager(ViewManagerDependencies(
            create_view=lambda view_id: view_catalog.create(view_id, self),
            get_current_save_path=lambda: self.current_save_path,
            get_selected_view_id=lambda: self.selected_view_id,
            build_error_placeholder=(
                self.dialog_manager.build_error_placeholder
            ),
            update_page=self.page.update,
            log=self.log,
            translate=self._t,
        ))

        # 进度管理器
        self.progress_manager = ProgressManager(self.page, self._t)

        # GUI优化管理器
        self.gui_optimizer = GUIOptimizer(GUIOptimizerDependencies(
            page=self.page,
            get_ui_setting=lambda key, default: self.config.ui_settings.get(
                key,
                default,
            ),
            save_config=self.config.save,
        ))

        # 当前存档状态和用例协调器
        self.current_save_store = CurrentSaveStore()
        self.current_save_store.subscribe_current(
            self._on_current_save_changed
        )
        self.current_save_store.subscribe_recent(
            self._on_recent_saves_changed
        )
        self.save_context_manager = SaveContextManager(
            config=self.config,
            store=self.current_save_store,
            pick_directory=self.dialog_manager.pick_directory,
            warn_dialog=self.dialog_manager.warn_dialog,
            error_dialog=self.dialog_manager.error_dialog,
            activate_save=self._activate_current_save,
            log=self.log,
        )

    def create_settings_view(self) -> ft.Control:
        """在组合根中装配设置页依赖。"""
        from app.ui.views.settings import (
            SettingsView,
            SettingsViewDependencies,
        )

        return SettingsView(SettingsViewDependencies(
            load_settings=self.config.get_settings,
            save_settings=self.config.update_settings,
            reset_settings=self._reset_settings,
            translate=self._t,
            apply_theme=self._apply_theme,
            apply_language=self._apply_language,
            set_sidebar_mode=self._set_sidebar_mode,
            set_log_panel_visible=self._set_log_panel_visible,
            configure_performance_monitor=(
                self.gui_optimizer.configure_performance_monitor
            ),
            set_performance_interval=(
                self.gui_optimizer.set_performance_print_interval
            ),
            info_dialog=self.info_dialog,
            error_dialog=self.error_dialog,
            pick_directory=self.pick_directory,
        ))

    def _apply_theme(self, theme: str) -> None:
        """将已持久化的主题选择应用到 Flet 壳层。"""
        get_theme_manager().set_mode(theme)
        self.page.bgcolor = THEME.bg_primary
        self.page.window.bgcolor = THEME.bg_primary
        self.page.theme_mode = (
            ft.ThemeMode.LIGHT if theme == "light" else ft.ThemeMode.DARK
        )
        self.page.update()

    def _apply_language(self, language: str) -> None:
        """切换当前翻译服务语言。"""
        self.i18n.set_language(language)

    def _set_sidebar_mode(self, mode: str) -> None:
        """应用侧栏偏好，同时保留窄窗口的强制折叠约束。"""
        del mode
        if not hasattr(self, "_sidebar"):
            return
        self.window_manager.refresh_responsive_layout()

    def _set_log_panel_visible(self, visible: bool) -> None:
        """同步日志入口和悬浮面板可见性。"""
        if not hasattr(self, "_log_fab"):
            return
        self._log_fab.set_visible(visible)
        self.floating_log_panel.set_visible(False)

    def _reset_settings(self) -> None:
        """重置配置并同步所有即时生效的设置。"""
        self.config.reset_config()
        settings = self.config.get_settings()
        self._apply_theme(settings.theme)
        self._apply_language(settings.language)
        self._set_sidebar_mode(settings.sidebar_mode)
        self._set_log_panel_visible(settings.show_log_panel)
        self.gui_optimizer.configure_performance_monitor(
            settings.enable_performance_monitor,
            float(settings.performance_print_interval),
        )

    def _on_current_save_changed(
        self,
        context: Optional[CurrentSaveContext],
    ) -> None:
        """Reflect selected-save state in UI adapters."""
        if hasattr(self, "_sidebar"):
            if context is None:
                self._sidebar.set_current_save_name(None)
            else:
                self._sidebar.set_current_save_name(
                    context.name,
                    context.display_path,
                )

        if context is None or not hasattr(self, "gui_optimizer"):
            return
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager:
            notification_manager.show_success(
                f"当前存档已设置为 {context.name}，相关功能将自动使用该存档"
            )
        # 后台按 UI 语言导入原版物品/方块名称，避免阻塞存档切换。
        self._schedule_auto_import_mc_language(context)

    def _on_recent_saves_changed(
        self,
        recent_saves: tuple[RecentSave, ...],
    ) -> None:
        """Reflect an immutable recent-save snapshot in the sidebar."""
        if hasattr(self, "_sidebar"):
            self._sidebar.set_recent_saves(
                [save.to_dict() for save in recent_saves]
            )

    def _activate_current_save(self, path: str) -> None:
        """Navigate to Explorer after the store has selected ``path``."""
        del path
        if hasattr(self, "_sidebar") and self._sidebar.selected_id != "explorer":
            self._sidebar.select_tab("explorer")
            return
        self.view_manager.switch_view("explorer")

    def _schedule_auto_import_mc_language(
        self,
        context: CurrentSaveContext,
    ) -> None:
        """在后台线程导入当前存档对应的原版语言文件。

        快速重复选择同一存档会去重；切换到新存档会提升 generation，
        使旧线程的通知与失败回滚失效。

        Args:
            context: 当前已选中的有效存档上下文。
        """
        if not self.config.is_auto_import_mc_lang_enabled():
            return

        save_path = str(context.path).strip()
        if not save_path:
            return

        with self._auto_lang_import_lock:
            if self._auto_lang_import_path == save_path:
                return
            self._auto_lang_import_path = save_path
            self._auto_lang_import_generation += 1
            generation = self._auto_lang_import_generation

        previous_task = self._auto_lang_import_task
        if previous_task is not None:
            previous_task.cancel()
        try:
            self._auto_lang_import_task = self.execution_runtime.submit(
                "auto_import_minecraft_language",
                lambda token: self._auto_import_mc_language_worker(
                    save_path,
                    generation,
                    token,
                ),
            )
        except (RuntimeClosedError, TaskQueueFullError) as exc:
            self._handle_auto_import_failure(save_path, generation, exc)

    def _auto_import_mc_language_worker(
        self,
        save_path: str,
        generation: int,
        cancellation: Optional[CancellationToken] = None,
    ) -> None:
        """解析 .minecraft 并导入 UI 语言对应的原版语言表。

        Args:
            save_path: 触发导入的存档绝对路径。
            generation: 调度时捕获的代数；过期结果会被丢弃。
        """
        if cancellation is not None and cancellation.is_cancelled:
            return
        try:
            locale = self.item.normalize_locale(self.i18n.current_language)
            configured = self.config.get_minecraft_dir()
            configured_dir = Path(configured) if configured else None
            result = self.item.import_language_from_local_minecraft(
                locale=locale,
                configured_dir=configured_dir,
                start_path=Path(save_path),
            )
        except (OSError, ValueError, TypeError, RuntimeError) as exc:
            self._handle_auto_import_failure(save_path, generation, exc)
            return
        except Exception as exc:
            # 语言导入依赖本地文件/zip/json，边界兜底避免后台线程静默崩溃。
            self._handle_auto_import_failure(save_path, generation, exc)
            return

        if (
            cancellation is not None
            and cancellation.is_cancelled
        ) or not self._is_auto_import_current(save_path, generation):
            return

        if result.count <= 0:
            self.log(
                f"自动导入语言未找到可用文件（locale={locale}）",
                "WARN",
            )
            return

        source = result.sources[0] if result.sources else "unknown"
        self.log(
            f"已自动导入 Minecraft 语言 {result.count} 项"
            f"（{result.locale}，{source}）",
            "INFO",
        )
        message = self._t(
            "settings.auto_import_mc_lang_ok",
            "已自动导入 {count} 个 Minecraft 名称（{locale}）",
            count=result.count,
            locale=result.locale,
        )
        run_on_ui(self.page, self._notify_auto_import_success, message)

    def _is_auto_import_current(self, save_path: str, generation: int) -> bool:
        """判断后台导入结果是否仍对应当前选择。"""
        with self._auto_lang_import_lock:
            return (
                self._auto_lang_import_generation == generation
                and self._auto_lang_import_path == save_path
            )

    def _handle_auto_import_failure(
        self,
        save_path: str,
        generation: int,
        exc: BaseException,
    ) -> None:
        """记录失败并在结果仍有效时允许同路径重试。"""
        self.log(f"自动导入 Minecraft 语言失败: {exc}", "ERROR")
        with self._auto_lang_import_lock:
            if (
                self._auto_lang_import_generation == generation
                and self._auto_lang_import_path == save_path
            ):
                self._auto_lang_import_path = None

    def _notify_auto_import_success(self, message: str) -> None:
        """在 UI 线程显示自动导入成功提示。"""
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager is not None:
            notification_manager.show_success(message)

    def _sync_config_to_migration(self) -> None:
        """同步配置到迁移参数"""
        self.migration_controller.sync_config_to_migration()

    def _start_migration_worker(
        self,
        operation: str,
        target: Callable[[str], None],
        destination: str,
    ) -> OperationHandle[None]:
        """通过应用运行时启动迁移控制器的外层后台操作。"""
        return self.execution_runtime.submit(
            operation,
            lambda cancellation: self._run_migration_target(
                target,
                destination,
                cancellation,
            ),
            lane=ExecutionLane.CPU,
            priority=TaskPriority.INTERACTIVE,
        )

    @staticmethod
    def _run_migration_target(
        target: Callable[[str], None],
        destination: str,
        cancellation: CancellationToken,
    ) -> None:
        """在任务开始与结束的安全点检查迁移取消请求。"""
        cancellation.raise_if_cancelled()
        target(destination)
        cancellation.raise_if_cancelled()

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════

    def _build_ui(self) -> None:
        """构建并绑定应用主壳层。"""
        shell = build_application_shell(ApplicationShellDependencies(
            page=self.page,
            translate=self._t,
            on_tab_select=self.view_manager.switch_view,
            on_tabs_reorder=self._on_tabs_reorder,
            on_import_save=self.save_context_manager.on_import_save,
            on_recent_save_select=(
                self.save_context_manager.on_recent_save_select
            ),
            recent_saves=self.save_context_manager.get_recent_saves(),
            show_log_panel=self.config.ui_settings.get(
                "show_log_panel",
                True,
            ),
            progress_control=self.progress_manager.create_progress_ui(),
            title_bar=self.window_manager.build_title_bar(),
        ))
        self._tab_defs = shell.tab_defs
        self._content = shell.content
        self._sidebar = shell.sidebar
        self._scrollable_content = shell.scrollable_content
        self.floating_log_panel = shell.floating_log_panel
        self._log_fab = shell.log_button
        self._main_row = shell.main_row
        self._shell = shell.shell
        self.view_manager.attach_host(ViewHost(content=shell.content))
        self.window_manager.attach_responsive_host(ResponsiveShellHost(
            sidebar=self._sidebar,
            main_row=self._main_row,
            shell=self._shell,
            scrollable_content=self._scrollable_content,
            content=self._content,
        ))
        self.window_manager.refresh_responsive_layout()
        self.page.add(shell.frame)

    def _on_tabs_reorder(self, tabs: list) -> None:
        """侧边栏标签页排序变更回调

        Args:
            tabs: 排序后的标签页列表
        """
        self._tab_defs = list(tabs)

    def _init_logging(self) -> None:
        """初始化日志系统"""
        def ui_log_callback(message: str, tag: str) -> None:
            ts = time.strftime("%H:%M:%S")
            self.floating_log_panel.log(f"[{ts}] [{tag.upper()}] {message}", tag.lower())

        setup_default_logging(
            enable_console=True,
            enable_file=True,
            file_path=None,
            enable_ui=True,
            ui_callback=ui_log_callback,
            level=LogLevel.INFO,
        )
        logger.info("MCSaveHelper 应用启动", module="App")

    # ════════════════════════════════════════════
    #  异常处理
    # ════════════════════════════════════════════

    def _on_page_error(self, e: ft.Event[ft.Page]) -> None:
        """页面级全局异常兜底

        Args:
            e: 控制事件
        """
        error_msg = str(e.data) if hasattr(e, 'data') else str(e)
        print(f"[PAGE ERROR] {error_msg}")
        traceback.print_exc()

        try:
            self.log(f"未捕获的异常: {error_msg}", "ERROR")

            # 使用优化的错误报告对话框
            if hasattr(self, 'gui_optimizer') and self.gui_optimizer.notification_manager:
                try:
                    from app.ui.feedback import ErrorReportDialog
                    exception = Exception(error_msg)
                    error_dialog = ErrorReportDialog(
                        self.page,
                        error=exception,
                        context="页面错误"
                    )
                    error_dialog.show()
                except Exception:
                    # 降级到原始错误对话框
                    self.dialog_manager.error_dialog(
                        self._t("dialogs.error", "错误"),
                        f"发生意外错误: {error_msg}",
                    )
            else:
                self.dialog_manager.error_dialog(
                    self._t("dialogs.error", "错误"),
                    f"发生意外错误: {error_msg}",
                )
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    # ════════════════════════════════════════════
    #  便捷方法（向后兼容）
    # ════════════════════════════════════════════

    def translate(self, key: str, default: str = "", **kwargs) -> str:
        """翻译公开端口，供视图使用。"""
        return self._t(key, default, **kwargs)

    def _t(self, key: str, default: str = "", **kwargs) -> str:
        """翻译快捷方法

        Args:
            key: 翻译键
            default: 默认文本
            **kwargs: 格式化参数

        Returns:
            str: 翻译后的文本
        """
        try:
            return self.i18n.translate(key, default, **kwargs)
        except Exception:
            # Translation failures must never crash UI text rendering.
            return default

    # ─── 日志方法 ───────────────────────────────
    def log(self, msg: str, level: str = "INFO") -> None:
        """记录日志

        Args:
            msg: 日志消息
            level: 日志级别
        """
        log_level = LogLevel.from_string(level)
        logger.log(log_level, msg, module="App")

    def log_header(self, msg: str) -> None:
        """记录标题日志

        Args:
            msg: 标题消息
        """
        self.floating_log_panel.log(f"\n{'=' * 50}", "separator")
        self.floating_log_panel.log(msg, "header")
        self.floating_log_panel.log(f"{'=' * 50}", "separator")

    def clear_log(self) -> None:
        """清空日志面板"""
        self.floating_log_panel._clear()

    # ─── 进度方法（委托给 ProgressManager）────────
    def update_progress(self, value: float) -> None:
        """更新进度条

        Args:
            value: 进度值（0.0 到 1.0）
        """
        self.progress_manager.update_progress(value)

    def show_progress(self, task_name: str = "") -> None:
        """显示进度条

        Args:
            task_name: 任务名称
        """
        self.progress_manager.show_progress(task_name)

    def hide_progress(self) -> None:
        """隐藏进度条"""
        self.progress_manager.hide_progress()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新进度条（带任务名称）

        Args:
            task_name: 任务名称
            value: 进度值（0.0 到 1.0）
        """
        self.progress_manager.update_progress_with_task(task_name, value)

    def set_progress_label(self, text: str) -> None:
        """设置进度标签文本

        Args:
            text: 标签文本
        """
        self.progress_manager.set_progress_label(text)

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        self.progress_manager.set_progress_value(value)

    def _copy_to_clipboard(self, text: str) -> None:
        """Adapt Flet 0.85's async clipboard service to a sync command."""
        self.page.run_task(self.page.clipboard.set, text)

    def _show_snackbar(
        self,
        message: str,
        bgcolor: str,
        duration: int,
    ) -> None:
        """Show transient feedback through Flet's dialog-control API."""
        self.page.show_dialog(ft.SnackBar(
            content=ft.Text(message, color=THEME.text_primary),
            bgcolor=bgcolor,
            duration=duration,
        ))

    # ─── 对话框方法（委托给 DialogManager）────────
    def info_dialog(self, title: str, message: str) -> None:
        """显示信息对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self.dialog_manager.info_dialog(title, message)

    def warn_dialog(self, title: str, message: str) -> None:
        """显示警告对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self.dialog_manager.warn_dialog(title, message)

    def error_dialog(
        self,
        title: str,
        message: str,
        exception: Optional[Exception] = None,
        show_details: bool = False
    ) -> None:
        """显示错误对话框

        Args:
            title: 对话框标题
            message: 对话框消息
            exception: 异常对象
            show_details: 是否显示异常详情
        """
        self.dialog_manager.error_dialog(title, message, exception, show_details)

    def _show_success(self, title: str, message: str) -> None:
        """Present success through notifications with a dialog fallback."""
        notification_manager = self.gui_optimizer.notification_manager
        if notification_manager:
            notification_manager.show_success(message)
            return
        self.info_dialog(title, message)

    def handle_exception(
        self,
        exception: Exception,
        title: Optional[str] = None,
        log: bool = True,
        show_dialog: bool = True
    ) -> None:
        """统一异常处理方法

        Args:
            exception: 异常对象
            title: 对话框标题
            log: 是否记录日志
            show_dialog: 是否显示对话框
        """
        self.dialog_manager.handle_exception(exception, title, log, show_dialog)

    # ─── 文件选择方法（委托给 DialogManager）──────
    def pick_directory(self) -> Optional[str]:
        """选择目录对话框

        Returns:
            Optional[str]: 选择的目录路径
        """
        return self.dialog_manager.pick_directory()

    def pick_file(
        self,
        title: str = "",
        file_types: Optional[List[FileType]] = None
    ) -> Optional[str]:
        """选择文件对话框

        Args:
            title: 对话框标题
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径
        """
        return self.dialog_manager.pick_file(title, file_types)

    def pick_files(
        self,
        title: str = "",
        file_types: Optional[List[FileType]] = None,
    ) -> Optional[List[str]]:
        """Multi-select file dialog."""
        return self.dialog_manager.pick_files(title, file_types)

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[List[FileType]] = None
    ) -> Optional[str]:
        """保存文件对话框

        Args:
            title: 对话框标题
            default_ext: 默认扩展名
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径
        """
        return self.dialog_manager.save_file(title, default_ext, file_types)

    # ════════════════════════════════════════════
    #  迁移入口（向后兼容）
    # ════════════════════════════════════════════

    def set_start_button_enabled(self, enabled: bool) -> None:
        """设置开始转换按钮的启用状态

        Args:
            enabled: 是否启用
        """
        self.view_manager.set_top_actions_enabled(enabled)

    def start(self) -> None:
        """开始转换按钮回调"""
        self.migration_controller.start()

    def _try_update_page(self) -> None:
        """尝试更新页面，忽略错误"""
        self.migration_controller.try_update_page()

    def _save_config(self) -> None:
        """保存当前配置"""
        self.migration_controller.save_config()

    def _run_single_thread(self, dest_dir: str) -> None:
        """执行单存档迁移的线程函数

        Args:
            dest_dir: 目标目录
        """
        self.migration_controller.run_single_thread(dest_dir)

    def _run_batch_thread(self, dest_dir: str) -> None:
        """执行批量迁移的线程函数

        Args:
            dest_dir: 目标目录
        """
        self.migration_controller.run_batch_thread(dest_dir)

    def open_folder(self, path: str) -> None:
        """在系统文件管理器中打开目录

        Args:
            path: 目录路径
        """
        self.migration_controller.open_folder(path)

    def set_src(self) -> None:
        """设置源目录"""
        try:
            path = self.pick_directory()
            if path:
                self.config.migration.src_path = path
                self._update_migrator_path("source", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def set_dest(self) -> None:
        """设置目标目录"""
        try:
            path = self.pick_directory()
            if path:
                self.config.migration.dest_path = path
                self._update_migrator_path("destination", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def set_batch_dir(self) -> None:
        """设置批量目录"""
        try:
            path = self.pick_directory()
            if path:
                self.config.migration.batch_dir_path = path
                self._update_migrator_path("batch", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def _update_migrator_path(self, target: str, value: str) -> None:
        """通过公开页面命令更新 MigratorView 路径。

        Args:
            target: source、destination 或 batch
            value: 字段值
        """
        view = self.view_manager.get_view("migrator")
        setter = getattr(view, "set_path_value", None)
        if callable(setter):
            setter(target, value)

    def update_uuid_mappings(self, mappings: Dict[str, str]) -> None:
        """UUID 映射变更回调

        Args:
            mappings: UUID 映射字典
        """
        self.config.custom_uuid_mappings = mappings
        self._save_config()

    # ════════════════════════════════════════════
    #  公共状态访问
    # ════════════════════════════════════════════

    @property
    def config(self) -> ConfigService:
        """应用配置服务（持久化 UI/路径/映射等）。"""
        return self.services.config

    @property
    def i18n(self) -> I18nService:
        """国际化翻译服务。"""
        return self.services.i18n

    @property
    def migration(self) -> MigrationService:
        """存档迁移业务服务。"""
        return self.services.migration

    @property
    def uuid(self) -> UUIDService:
        """UUID 映射与转换服务。"""
        return self.services.uuid

    @property
    def item(self) -> ItemService:
        """物品名称/语言与解析服务。"""
        return self.services.item

    @property
    def texture(self) -> TextureService:
        """方块/物品贴图导入与查询服务。"""
        return self.services.texture

    @property
    def execution_runtime(self) -> ExecutionRuntime:
        """应用级有界后台任务运行时。"""
        return self.services.execution_runtime

    def create_region_map_service(self) -> RegionMapService:
        """Create a map service owned by one Explorer view lifecycle."""
        from app.services.region_map_service import RegionMapService

        return RegionMapService()

    @property
    def selected_view_id(self) -> Optional[str]:
        """Public read-only access to the selected sidebar view."""
        return self._sidebar.selected_id if hasattr(self, "_sidebar") else None

    @property
    def current_save_path(self) -> Optional[str]:
        """Public read-only access to the selected save path."""
        return self.save_context_manager.get_current_save_path()
