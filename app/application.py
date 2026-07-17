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

import time
import traceback
from typing import TYPE_CHECKING, Optional, List, Dict
import flet as ft

from core.logger import LogLevel, logger, setup_default_logging

from app.bootstrap.services import AppServices, create_app_services
from app.models.save_context import CurrentSaveContext
from app.models.save_store import CurrentSaveStore, RecentSave
from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)

from app.ui.theme import THEME, mc_border, mc_shadow, get_theme_manager
from app.ui.icons import IconSet
from app.ui.sidebar import Sidebar
from app.ui.view_catalog import create_default_view_catalog
from app.ui.components.floating_log_panel import FloatingLogPanel, FloatingLogButton

# 导入管理器
from app.core.window_manager import WindowManager
from app.core.dialog_manager import DialogManager
from app.core.view_manager import (
    ViewHost,
    ViewManager,
    ViewManagerDependencies,
)
from app.core.progress_manager import ProgressManager
from app.core.gui_optimizer import GUIOptimizer
from app.core.save_context_manager import SaveContextManager

if TYPE_CHECKING:
    from app.services.config_service import ConfigService
    from app.services.i18n_service import I18nService
    from app.services.migration_service import MigrationService
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
            pass  # 默认暗色主题

    def _init_managers(self) -> None:
        """初始化所有管理器"""
        # 窗口管理器
        self.window_manager = WindowManager(self)
        self.window_manager.setup_window()

        # 对话框管理器
        self.dialog_manager = DialogManager(self)

        # 视图管理器
        view_catalog = create_default_view_catalog()
        self.view_manager = ViewManager(ViewManagerDependencies(
            create_view=lambda view_id: view_catalog.create(view_id, self),
            get_current_save_path=lambda: self.current_save_path,
            get_selected_view_id=lambda: self.selected_view_id,
            build_error_placeholder=(
                self.dialog_manager.build_error_placeholder
            ),
            update_page=self.page.update,
            log=self.log,
        ))

        # 进度管理器
        self.progress_manager = ProgressManager(self)

        # GUI优化管理器
        self.gui_optimizer = GUIOptimizer(self)

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

    def _sync_config_to_migration(self) -> None:
        """同步配置到迁移参数"""
        self.migration_controller.sync_config_to_migration()

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════

    def _build_ui(self) -> None:
        """构建应用主界面 - Modernized Minecraft aesthetic"""
        # 标签页定义
        self._tab_defs = [
            {
                "id": "explorer",
                "label": self._t("sidebar.explorer", "存档浏览器"),
                "icon": IconSet.MAP,
            },
            {
                "id": "migrator",
                "label": self._t("sidebar.migrator", "存档转换"),
                "icon": IconSet.PACKAGE,
            },
            {
                "id": "save_repair",
                "label": self._t("sidebar.save_repair", "存档修复"),
                "icon": IconSet.BUILD,
            },
            {
                "id": "map_export",
                "label": self._t("sidebar.map_export", "地图导出"),
                "icon": IconSet.EXPORT,
            },
            {
                "id": "compare",
                "label": self._t("sidebar.compare", "存档对比"),
                "icon": IconSet.BALANCE,
            },
            {
                "id": "mappings",
                "label": self._t("sidebar.mappings", "映射管理"),
                "icon": IconSet.LINK,
            },
            {
                "id": "server_properties",
                "label": self._t("sidebar.server_properties", "服务器配置"),
                "icon": IconSet.CLIPBOARD,
            },
            {
                "id": "settings",
                "label": self._t("sidebar.settings", "设置"),
                "icon": IconSet.SETTINGS,
            },
        ]

        # 创建内容容器 - Enhanced with better styling
        self._content: ft.Container = ft.Container(
            padding=20,
            bgcolor=THEME.bg_card,
            border=mc_border(3),
            border_radius=8,
            expand=True,
        )

        # 创建顶部操作按钮容器
        self._top_actions = ft.Row(
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._top_actions.visible = False

        self.view_manager.attach_host(ViewHost(
            content=self._content,
            top_actions=self._top_actions,
        ))

        # 创建侧边栏
        self._sidebar = Sidebar(
            tabs=self._tab_defs,
            on_tab_select=self.view_manager.switch_view,
            on_tabs_reorder=self._on_tabs_reorder,
            on_import_save=self.save_context_manager.on_import_save,
            on_set_current_save=self.save_context_manager.on_import_save,
            on_recent_save_select=self.save_context_manager.on_recent_save_select,
            recent_saves=self.save_context_manager.get_recent_saves(),
            default_tab="explorer",
        )

        # 构建顶部栏
        top_bar = self._build_top_bar()

        # 可滚动内容区域 - Enhanced padding
        self._scrollable_content = ft.Container(
            content=self._content,
            padding=16,
            expand=True,
        )

        content_area = ft.Column(
            [top_bar, self._scrollable_content],
            spacing=0,
            expand=True,
        )

        # 日志面板设置
        self.floating_log_panel = FloatingLogPanel(
            page=self.page,
            title=self._t("log_panel.title", "日志"),
        )

        # 日志悬浮球按钮
        self._log_fab = FloatingLogButton(
            floating_panel=self.floating_log_panel,
            page=self.page,
        )

        # 初始化时根据配置设置可见性
        show_log = self.config.ui_settings.get("show_log_panel", True)
        self._log_fab.set_visible(show_log)
        self.floating_log_panel.set_visible(False)

        # 右侧面板（内容 + 日志）
        right_panel = ft.Stack(
            [
                content_area,
                self.floating_log_panel,
                self._log_fab,
            ],
            expand=True,
        )

        # 主行 - Enhanced spacing
        self._main_row = ft.Row(
            [self._sidebar, right_panel],
            spacing=14,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )

        # 外壳 - Modernized with subtle gradient effect
        self._shell = ft.Container(
            content=self._main_row,
            padding=14,
            margin=ft.Margin(left=14, right=14, top=0, bottom=14),
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=ft.BorderSide(4, THEME.border_light),
                top=None,
                right=ft.BorderSide(4, THEME.border_dark),
                bottom=ft.BorderSide(4, THEME.border_dark),
            ),
            border_radius=10,
            shadow=mc_shadow(6),
            expand=True,
        )

        # 底部进度条 - Enhanced styling
        progress_container = self.progress_manager.create_progress_ui()
        bottom_bar = ft.Container(
            content=ft.Container(
                content=progress_container,
                padding=ft.Padding(left=20, right=20, top=10, bottom=10),
                bgcolor=THEME.mc_wood,
                border_radius=6,
            ),
            bgcolor=THEME.mc_wood,
            border=ft.Border(
                left=ft.BorderSide(3, THEME.border_light),
                top=None,
                right=ft.BorderSide(3, THEME.border_dark),
                bottom=ft.BorderSide(3, THEME.border_dark),
            ),
            border_radius=8,
            margin=ft.Margin(left=14, right=14, top=0, bottom=14),
        )

        # 应用框架 - Enhanced layout
        app_frame = ft.Column(
            [self.window_manager.build_title_bar(), self._shell, bottom_bar],
            spacing=0,
            expand=True,
        )

        self.page.add(app_frame)

    def _build_top_bar(self) -> ft.Container:
        """构建顶部栏 - Modernized Minecraft aesthetic

        Returns:
            ft.Container: 顶部栏容器
        """
        return ft.Container(
            content=ft.Column(
                [
                    # Grass strip (Minecraft signature)
                    ft.Container(
                        height=6,
                        bgcolor=THEME.mc_grass,
                        border_radius=ft.BorderRadius(
                            top_left=8,
                            top_right=8,
                            bottom_left=0,
                            bottom_right=0,
                        ),
                    ),
                    # Main header content
                    ft.Container(
                        content=ft.Row(
                            [
                                # App identity
                                ft.Row(
                                    [
                                        ft.Container(
                                            content=ft.Icon(
                                                IconSet.PICKAXE,
                                                size=24,
                                                color=THEME.mc_gold,
                                            ),
                                            width=48,
                                            height=48,
                                            alignment=ft.alignment.Alignment(0, 0),
                                            bgcolor=THEME.bg_secondary,
                                            border=mc_border(2),
                                            border_radius=8,
                                        ),
                                        ft.Column(
                                            [
                                                ft.Text(
                                                    "MCSaveHelper",
                                                    size=20,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=THEME.text_primary,
                                                    font_family="monospace",
                                                ),
                                                ft.Text(
                                                    self._t("app.subtitle", "存档管理工具"),
                                                    size=11,
                                                    color=THEME.mc_grass,
                                                    font_family="monospace",
                                                ),
                                            ],
                                            spacing=3,
                                        ),
                                    ],
                                    spacing=14,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                # Action buttons
                                ft.Row(
                                    [self._top_actions],
                                    spacing=15,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(left=20, right=20, top=14, bottom=14),
                        bgcolor=THEME.mc_wood,
                    ),
                ],
                spacing=0,
            ),
            bgcolor=THEME.mc_wood,
            border=mc_border(3),
            border_radius=8,
        )

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

    def _on_page_error(self, e: ft.ControlEvent) -> None:
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
            pass

    # ════════════════════════════════════════════
    #  便捷方法（向后兼容）
    # ════════════════════════════════════════════

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
        file_types: Optional[List[tuple]] = None
    ) -> Optional[str]:
        """选择文件对话框

        Args:
            title: 对话框标题
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径
        """
        return self.dialog_manager.pick_file(title, file_types)

    def save_file(
        self,
        title: str = "",
        default_ext: str = ".txt",
        file_types: Optional[List[tuple]] = None
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
                self._update_migrator_field("_src_field", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def set_dest(self) -> None:
        """设置目标目录"""
        try:
            path = self.pick_directory()
            if path:
                self.config.migration.dest_path = path
                self._update_migrator_field("_dest_field", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def set_batch_dir(self) -> None:
        """设置批量目录"""
        try:
            path = self.pick_directory()
            if path:
                self.config.migration.batch_dir_path = path
                self._update_migrator_field("_batch_dir_field", path)
                self.page.update()
        except Exception as e:
            self.handle_exception(e, title="选择目录失败")

    def _update_migrator_field(self, field_name: str, value: str) -> None:
        """更新 MigratorView 中的输入框值

        Args:
            field_name: 字段名称
            value: 字段值
        """
        view = self.view_manager.get_view("migrator")
        field = getattr(view, field_name, None)
        if field is not None:
            field.value = value
            try:
                field.update()
            except RuntimeError:
                pass

    def _on_uuid_mappings_change(self, mappings: Dict[str, str]) -> None:
        """UUID 映射变更回调

        Args:
            mappings: UUID 映射字典
        """
        self.config.custom_uuid_mappings = mappings
        self._save_config()

    # ════════════════════════════════════════════
    #  属性访问（向后兼容）
    # ════════════════════════════════════════════

    @property
    def config(self) -> ConfigService:
        return self.services.config

    @property
    def i18n(self) -> I18nService:
        return self.services.i18n

    @property
    def migration(self) -> MigrationService:
        return self.services.migration

    @property
    def uuid(self) -> UUIDService:
        return self.services.uuid

    @property
    def views(self) -> Dict[str, ft.Control]:
        """获取视图字典

        Returns:
            Dict[str, ft.Control]: 视图字典
        """
        return self.view_manager.views

    @property
    def selected_view_id(self) -> Optional[str]:
        """Public read-only access to the selected sidebar view."""
        return self._sidebar.selected_id if hasattr(self, "_sidebar") else None

    @property
    def _current_save_context(self):
        """获取当前存档上下文"""
        return self.save_context_manager.get_current_save_context()

    @_current_save_context.setter
    def _current_save_context(self, value):
        """设置当前存档上下文"""
        if value is not None:
            self.save_context_manager.set_current_save_context(value)

    @property
    def _current_save_path(self) -> Optional[str]:
        """获取当前存档路径"""
        return self.current_save_path

    @_current_save_path.setter
    def _current_save_path(self, value: Optional[str]) -> None:
        """设置当前存档路径（内部使用）"""
        self.save_context_manager.set_current_save_path(value)

    @property
    def current_save_path(self) -> Optional[str]:
        """Public read-only access to the selected save path."""
        return self.save_context_manager.get_current_save_path()

    @property
    def _recent_saves(self) -> List[Dict[str, str]]:
        """获取最近存档列表"""
        return self.save_context_manager.get_recent_saves()

    @property
    def notification_manager(self):
        """获取通知管理器（向后兼容）"""
        return self.gui_optimizer.notification_manager if hasattr(self, 'gui_optimizer') else None

    @property
    def _heartbeat_active(self) -> bool:
        """获取心跳活动状态"""
        return self.gui_optimizer._heartbeat_active if hasattr(self, 'gui_optimizer') else False

    @_heartbeat_active.setter
    def _heartbeat_active(self, value: bool) -> None:
        """设置心跳活动状态"""
        if hasattr(self, 'gui_optimizer'):
            self.gui_optimizer._heartbeat_active = value

    @property
    def _hang_detector_active(self) -> bool:
        """获取卡死检测器活动状态"""
        return self.gui_optimizer._hang_detector_active if hasattr(self, 'gui_optimizer') else False

    @_hang_detector_active.setter
    def _hang_detector_active(self, value: bool) -> None:
        """设置卡死检测器活动状态"""
        if hasattr(self, 'gui_optimizer'):
            self.gui_optimizer._hang_detector_active = value
