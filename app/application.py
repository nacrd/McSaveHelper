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

from typing import Optional
import flet as ft


from app.bootstrap.services import AppServices, create_app_services
from app.adapters.file_dialogs import TkFileDialogs
from app.models.save_store import CurrentSaveStore
from app.application_facade import ApplicationFacadeMixin
from app.application_settings import SettingsCoordinationMixin
from app.application_shell_mixin import ApplicationShellMixin
from app.application_save_ui import SaveContextUiMixin
from app.application_lifecycle import (
    AutoLanguageImportSupport,
    MigrationRuntimeSupport,
)
from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)

from app.ui.theme import get_theme_manager
from app.ui.view_catalog import create_default_view_catalog
from app.ui.feature_context import FeatureContext
from app.ui.utils import run_on_ui

# 导入管理器
from app.core.window_manager import (
    WindowManager,
    WindowManagerDependencies,
)
from app.core.dialog_manager import DialogManager, DialogManagerDependencies
from app.core.view_manager import (
    ViewManager,
    ViewManagerDependencies,
)
from app.core.progress_manager import ProgressManager
from app.core.gui_optimizer import GUIOptimizer, GUIOptimizerDependencies
from app.core.save_context_manager import SaveContextManager


_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS = 5.0


class Application(
    AutoLanguageImportSupport,
    MigrationRuntimeSupport,
    SettingsCoordinationMixin,
    ApplicationShellMixin,
    SaveContextUiMixin,
    ApplicationFacadeMixin,
):
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
        self._init_auto_language_import_state()

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
                post_ui=lambda callback: run_on_ui(self.page, callback),
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
            dispose_views=self._dispose_views_and_migration,
            dispose_file_dialogs=self._file_dialogs.close,
            close_texture_service=self.texture.close,
            shutdown_execution_runtime=lambda: self.execution_runtime.shutdown(
                wait=True,
                timeout=_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS,
            ),
            close_world_indexes=self.services.world_indexes.close,
            close_cache_registry=self.services.cache_registry.close,
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
            settings_factory=lambda _app: self.create_settings_view(),
        )
        self.view_manager = ViewManager(ViewManagerDependencies(
            create_view=lambda view_id: view_catalog.create(
                view_id,
                FeatureContext(self),
            ),
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

    def _sync_config_to_migration(self) -> None:
        """同步配置到迁移参数"""
        self.migration_controller.sync_config_to_migration()

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════
