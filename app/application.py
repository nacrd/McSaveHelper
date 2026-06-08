"""Application Core —— 应用主协调器

替代原 ui/app.py 中的 App 类。职责：
  - 初始化所有服务（配置、UUID、迁移、国际化）
  - 管理 UI 全局状态（迁移参数、日志、进度）
  - 协调视图切换
  - 提供文件选择对话框
"""
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, List, Dict, Callable

import flet as ft

from core.logger import LogLevel, logger, setup_default_logging
from core.types import LogCallback, ProgressCallback

from app.models.config import MigrationConfig
from app.models.save_context import CurrentSaveContext
from app.services.config_service import ConfigService
from app.services.uuid_service import UUIDService
from app.services.migration_service import MigrationService
from app.services.i18n_service import I18nService
from app.controllers.migration_controller import MigrationController

from app.ui.theme import THEME, mc_border, mc_shadow
from app.ui.sidebar import Sidebar
from app.ui.components.buttons import btn_primary, btn_danger
from app.ui.components.floating_log_panel import FloatingLogPanel, FloatingLogButton

# GUI 优化模块
from app.ui.keyboard_shortcuts import (
    shortcut_manager,
    register_default_shortcuts,
    ModifierKey
)
from app.ui.performance import perf_monitor, resource_monitor, Timer, health_monitor, AlertLevel
from app.ui.hang_detector import get_hang_detector
from app.ui.feedback import ErrorReportDialog
from app.ui.notifications import NotificationManager
from app.ui.accessibility import validate_theme_accessibility


@dataclass(frozen=True)
class TopAction:
    """Descriptor for a page-level top-bar action."""

    label: str
    handler: Callable[[ft.ControlEvent], None]
    style: str = "primary"


class Application:
    """MCSaveHelper 应用核心"""

    def __init__(self, page: ft.Page) -> None:
        self.page: ft.Page = page
        self._current_dialog: Optional[ft.AlertDialog] = None
        self._shutdown_started = False

        # 全局异常兜底
        page.on_error = self._on_page_error

        # ─── 初始化服务（逐个 try，失败降级） ─────
        try:
            self.i18n: I18nService = I18nService()
        except Exception as e:
            print(f"[WARN] I18nService 初始化失败: {e}")
            self.i18n = I18nService.__new__(I18nService)
            self.i18n._manager = None
            self.i18n.translate = lambda key, default="", **kw: default  # type: ignore

        try:
            self.config: ConfigService = ConfigService()
        except Exception as e:
            print(f"[WARN] ConfigService 初始化失败: {e}")
            self.config = ConfigService.__new__(ConfigService)
            self.config._config = {}  # type: ignore
            self.config._migration = MigrationConfig()  # type: ignore
            self.config.save = lambda: None  # type: ignore

        # ─── 初始化 GUI 优化模块（必须在 config 之后）─────────────────
        self._init_gui_optimizations()

        try:
            self.migration: MigrationService = MigrationService(self.config)
        except Exception as e:
            print(f"[WARN] MigrationService 初始化失败: {e}")
            self.migration = MigrationService.__new__(
                MigrationService)  # type: ignore

        try:
            self.uuid: UUIDService = UUIDService()
        except Exception as e:
            print(f"[WARN] UUIDService 初始化失败: {e}")
            self.uuid = UUIDService.__new__(UUIDService)  # type: ignore

        self.migration_controller = MigrationController(self)

        # ─── 同步配置到迁移参数 ─────────────────
        self._sync_config_to_migration()

        # ─── UI 组件 ────────────────────────────
        # 使用美化的进度条组件
        from app.ui.components.progress import McProgressBar
        self._progress_bar: McProgressBar = McProgressBar(
            value=0.0,
            color=THEME.mc_diamond,
            height=8,
            show_percentage=False,
            animated=True,
        )
        self._progress_label: ft.Text = ft.Text(
            self._t("top_bar.ready", "就绪"),
            size=12,
            color=THEME.mc_gold,
            weight=ft.FontWeight.BOLD,
            font_family="monospace",
        )
        # 进度条容器（默认隐藏）
        self._progress_container: ft.Container = ft.Container(
            content=ft.Row(
                [self._progress_label, self._progress_bar],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,  # 默认隐藏
        )
        self._top_actions = ft.Row(
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._top_actions.visible = False

        # ─── 视图容器 ───────────────────────────
        self.views: Dict[str, ft.Control] = {}
        self._content: ft.Container = ft.Container(
            padding=18,
            bgcolor=THEME.bg_card,
            border=mc_border(3),
        )
        self._content.expand = True

        # ─── 构建 UI ────────────────────────────
        self._setup_page()
        self._init_logging()
        self._build_ui()
        self._switch_view("explorer")
        page.update()

    # ════════════════════════════════════════════
    #  初始化
    # ════════════════════════════════════════════

    def _init_gui_optimizations(self) -> None:
        """初始化 GUI 优化功能"""
        try:
            # 1. 初始化通知管理器
            self.notification_manager = NotificationManager(self.page)

            # 2. 启用独立的卡死检测器（静默启用，输出到日志）
            hang_detector = get_hang_detector()
            hang_detector.enable()
            self._start_hang_detector_heartbeat()

            # 3. 根据配置启用性能监控（可选）
            enable_perf = self.config.ui_settings.get(
                "enable_performance_monitor", False)

            if enable_perf:
                perf_monitor.enable()
                resource_monitor.start()
                interval = float(
                    self.config.ui_settings.get(
                        "performance_print_interval", 60))
                resource_monitor.set_print_interval(max(5.0, interval))
                # 配置健康监控告警回调
                health_monitor.set_alert_callback(self._on_health_alert)
                self._start_heartbeat()

            # 4. 注册键盘快捷键
            register_default_shortcuts(
                on_save=self._shortcut_save_config,
                on_help=self._shortcut_show_help,
                on_refresh=self._shortcut_refresh
            )

            # 注册应用特定快捷键
            shortcut_manager.register(
                "show_feedback",
                "f",
                self._shortcut_show_feedback,
                "显示反馈对话框",
                [ModifierKey.CTRL]
            )

            # 设置键盘事件处理
            self.page.on_keyboard_event = self._on_keyboard_event

            # 4. 验证可访问性
            accessibility_results = validate_theme_accessibility()
            failed_checks = [
                name for name, result in accessibility_results.items()
                if not result["passes"]
            ]
            if failed_checks:
                logger.warning(
                    f"可访问性检查: {len(failed_checks)} 项未通过",
                    module="accessibility"
                )
            else:
                logger.info("可访问性检查: 全部通过", module="accessibility")

            logger.info("GUI 优化模块初始化完成", module="App")

        except Exception as e:
            logger.error(f"GUI 优化模块初始化失败: {e}", module="App")
            # 降级：不使用优化功能
            self.notification_manager = None  # type: ignore

    def _on_keyboard_event(self, e: ft.KeyboardEvent) -> None:
        """处理键盘事件

        Args:
            e: 键盘事件
        """
        try:
            shortcut_manager.handle_event(e)
        except Exception as ex:
            logger.error(f"键盘事件处理失败: {ex}", module="App")

    def _shortcut_save_config(self, e) -> None:
        """快捷键：保存配置 (Ctrl+S)"""
        try:
            with Timer("save_config"):
                self.config.save()
            logger.info("配置已保存", module="App")
            if self.notification_manager:
                self.notification_manager.show_success("配置保存成功")
        except Exception as ex:
            logger.error(f"保存配置失败: {ex}", module="App")
            if self.notification_manager:
                self.notification_manager.show_error("保存配置失败")

    def _shortcut_show_help(self, e) -> None:
        """快捷键：显示帮助 (F1)"""
        try:
            help_dialog = shortcut_manager.create_help_dialog()
            self.page.dialog = help_dialog
            help_dialog.open = True
            self.page.update()
        except Exception as ex:
            logger.error(f"显示帮助失败: {ex}", module="App")

    def _shortcut_refresh(self, e) -> None:
        """快捷键：刷新页面 (F5)"""
        try:
            logger.info("刷新页面", module="App")
            self.page.update()
            if self.notification_manager:
                self.notification_manager.show_info("页面已刷新")
        except Exception as ex:
            logger.error(f"刷新页面失败: {ex}", module="App")

    def _shortcut_show_feedback(self, e) -> None:
        """快捷键：显示反馈对话框 (Ctrl+F)"""
        try:
            from app.ui.feedback import FeedbackDialog
            feedback_dialog = FeedbackDialog(self.page)
            feedback_dialog.show()
        except Exception as ex:
            logger.error(f"显示反馈对话框失败: {ex}", module="App")

    # ─── 健康监控 ────────────────────────────────

    def _on_health_alert(self, alert) -> None:
        """健康告警回调 — 通过通知系统提示用户"""
        # 关闭时不显示告警通知
        try:
            from app.ui.utils import is_app_closing
            if is_app_closing():
                return
        except Exception:
            pass

        if not self.notification_manager:
            return
        try:
            if alert.level == AlertLevel.CRITICAL:
                async def _show_error(message: str):
                    self.notification_manager.show_error(
                        message, duration_ms=8000)
                self.page.run_task(_show_error, alert.message)
            else:
                async def _show_warning(message: str):
                    self.notification_manager.show_warning(
                        message, duration_ms=5000)
                self.page.run_task(_show_warning, alert.message)
        except Exception:
            pass

    def _start_heartbeat(self) -> None:
        """启动 UI 心跳线程，用于卡死检测"""
        import threading as _threading

        def _beat_loop():
            while getattr(self, '_heartbeat_active', False):
                health_monitor.heartbeat()
                _threading.Event().wait(3.0)

        self._heartbeat_active = True
        t = _threading.Thread(target=_beat_loop, daemon=True)
        t.start()

    def _start_hang_detector_heartbeat(self) -> None:
        """启动独立的卡死检测器心跳线程（始终运行）"""
        import threading as _threading

        def _hang_beat_loop():
            hang_detector = get_hang_detector()
            while getattr(self, '_hang_detector_active', False):
                hang_detector.ui_heartbeat()
                _threading.Event().wait(2.0)  # 每 2 秒一次心跳

        self._hang_detector_active = True
        t = _threading.Thread(
            target=_hang_beat_loop,
            daemon=True,
            name="HangDetectorHeartbeat")
        t.start()

    # ════════════════════════════════════════════
    #  初始化
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
            if hasattr(
                    self,
                    'notification_manager') and self.notification_manager:
                try:
                    # 尝试创建异常对象
                    exception = Exception(error_msg)
                    error_dialog = ErrorReportDialog(
                        self.page,
                        error=exception,
                        context="页面错误"
                    )
                    error_dialog.show()
                except Exception:
                    # 降级到原始错误对话框
                    self.error_dialog(
                        self._t("dialogs.error", "错误"),
                        f"发生意外错误: {error_msg}",
                    )
            else:
                self.error_dialog(
                    self._t("dialogs.error", "错误"),
                    f"发生意外错误: {error_msg}",
                )
        except Exception:
            pass  # 连对话框都弹不出时只能打日志

    def _setup_page(self) -> None:
        """设置页面基本属性"""
        page = self.page
        page.title = self._t("app.title", "MCSaveHelper · 存档管理工具")
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = THEME.bg_primary
        page.window.bgcolor = THEME.bg_primary
        page.window.frameless = False
        page.window.title_bar_hidden = True
        page.window.title_bar_buttons_hidden = True
        page.window.resizable = True
        page.window.prevent_close = True
        page.window.on_event = self._on_window_event
        page.padding = 0
        page.window.width = 1100
        page.window.height = 820
        page.window.min_width = 800
        page.window.min_height = 600
        # 添加窗口大小变化监听（兼容不同版本的Flet）
        try:
            page.on_resize = self._on_window_resize
        except Exception:
            logger.warning("on_resize 事件不可用，跳过窗口大小监听", module="App")
        icon_path = self._resolve_icon_path()
        if icon_path:
            page.window.icon = icon_path

    def _on_window_resize(self, e) -> None:
        """窗口大小变化时的响应（带防抖，兼容版）

        Args:
            e: 窗口大小变化事件
        """
        try:
            # 防抖：取消上次延迟更新，延迟 150ms 后执行
            timer = getattr(self, '_resize_timer', None)
            if timer is not None:
                timer.cancel()

            import threading
            self._resize_timer = threading.Timer(0.15, self._apply_resize)
            self._resize_timer.daemon = True
            self._resize_timer.start()
        except Exception as ex:
            logger.error(f"窗口大小变化处理失败: {ex}", module="App")

    def _apply_resize(self) -> None:
        """实际执行窗口大小调整（在防抖延迟后调用）"""
        try:
            width = self.page.window.width
            height = self.page.window.height

            self._apply_responsive_layout(width, height)

            self.page.update()

            logger.debug(
                f"窗口大小变化: {width}x{height}",
                module="App"
            )
        except Exception as ex:
            logger.error(f"窗口大小变化处理失败: {ex}", module="App")

    def _apply_responsive_layout(self, width: float, height: float) -> None:
        compact = width < 980
        roomy = width >= 1300
        if hasattr(self, '_sidebar'):
            self._sidebar.set_width(170 if compact else 230 if roomy else 205)
        if hasattr(self, '_main_row'):
            self._main_row.spacing = 6 if compact else 12
        if hasattr(self, '_shell'):
            shell_pad = 6 if compact else 12
            shell_margin = 4 if compact else 12
            self._shell.padding = shell_pad
            self._shell.margin = ft.Margin(
                left=shell_margin,
                right=shell_margin,
                top=0,
                bottom=shell_margin)
        if hasattr(self, '_scrollable_content'):
            self._scrollable_content.padding = 6 if compact else 14
        if hasattr(self, '_content'):
            self._content.padding = 8 if compact else 18
        if hasattr(self, '_top_actions'):
            self._top_actions.spacing = 6 if compact else 8
            for btn in self._top_actions.controls:
                if hasattr(btn, 'height'):
                    btn.height = 34 if compact else 38
                if hasattr(btn, 'width') and compact:
                    btn.width = min(getattr(btn, 'width', 120) or 120, 104)
        current_view = self.views.get(
            self._sidebar.selected_id) if hasattr(
            self, '_sidebar') else None
        if current_view and hasattr(current_view, 'set_compact_mode'):
            current_view.set_compact_mode(compact)

    @staticmethod
    def _resolve_icon_path() -> Optional[str]:
        """解析应用图标路径，兼容开发环境和 PyInstaller 打包环境"""
        import sys
        icon_name = "mcsavehelper_icon.ico"
        candidates = []
        if hasattr(sys, '_MEIPASS'):
            candidates.append(Path(sys._MEIPASS) / icon_name)
            candidates.append(Path(sys.executable).parent / icon_name)
        candidates.append(Path(__file__).parent.parent / icon_name)
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _init_logging(self) -> None:
        """初始化日志系统"""
        def ui_log_callback(message: str, tag: str) -> None:
            ts = time.strftime("%H:%M:%S")
            self.floating_log_panel.log(
                f"[{ts}] [{tag.upper()}] {message}", tag.lower())

        setup_default_logging(
            enable_console=True, enable_file=True, file_path=None,
            enable_ui=True, ui_callback=ui_log_callback,
            level=LogLevel.INFO,
        )
        logger.info("MCSaveHelper 应用启动", module="App")

    def _sync_config_to_migration(self) -> None:
        """同步配置到迁移参数"""
        self.migration_controller.sync_config_to_migration()

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════

    def _build_ui(self) -> None:
        """构建应用主界面"""
        # 标签页定义
        self._tab_defs = [
            {"id": "explorer", "label": self._t("sidebar.explorer", "存档浏览器"), "icon": "🗺"},
            {"id": "migrator", "label": self._t("sidebar.migrator", "存档转换"), "icon": "📦"},
            {"id": "save_repair", "label": self._t("sidebar.save_repair", "存档修复"), "icon": "🔧"},
            {"id": "map_export", "label": self._t("sidebar.map_export", "地图导出"), "icon": "🗺"},
            {"id": "compare", "label": self._t("sidebar.compare", "存档对比"), "icon": "⚖"},
            {"id": "mappings", "label": self._t("sidebar.mappings", "映射管理"), "icon": "🔗"},
            {"id": "server_properties", "label": self._t("sidebar.server_properties", "服务器配置"), "icon": "📋"},
            {"id": "settings", "label": self._t("sidebar.settings", "设置"), "icon": "⚙"},
        ]
        # 当前设置的存档上下文（统一入口）
        self._current_save_context: Optional[CurrentSaveContext] = None
        self._current_save_path: Optional[str] = None
        self._recent_saves: List[Dict[str, str]] = self._load_recent_saves()
        self._sidebar = Sidebar(
            tabs=self._tab_defs,
            on_tab_select=self._switch_view,
            on_tabs_reorder=self._on_tabs_reorder,
            on_import_save=self._on_import_save,
            on_set_current_save=self._on_import_save,
            on_recent_save_select=self._on_recent_save_select,
            recent_saves=self._recent_saves,
            default_tab="explorer",
        )
        top_bar = self._build_top_bar()

        self._scrollable_content = ft.Container(
            content=self._content,
            padding=14,
            expand=True,
        )
        content_area = ft.Column(
            [top_bar, self._scrollable_content],
            spacing=0,
            expand=True,
        )

        # Log panel setup - 使用悬浮球日志面板
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

        right_panel = ft.Stack(
            [
                content_area,
                self.floating_log_panel,
                self._log_fab,
            ],
            expand=True,
        )

        self._main_row = ft.Row(
            [self._sidebar, right_panel],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )

        self._shell = ft.Container(
            content=self._main_row,
            padding=12,
            margin=ft.Margin(left=12, right=12, top=0, bottom=12),
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=ft.BorderSide(4, THEME.border_light),
                top=None,
                right=ft.BorderSide(4, THEME.border_dark),
                bottom=ft.BorderSide(4, THEME.border_dark),
            ),
            shadow=mc_shadow(6),
            expand=True,
        )

        # 底部进度条容器
        bottom_bar = ft.Container(
            content=ft.Container(
                content=self._progress_container,
                padding=ft.Padding(left=18, right=18, top=8, bottom=8),
                bgcolor=THEME.mc_wood,
            ),
            bgcolor=THEME.mc_wood,
            border=ft.Border(
                left=ft.BorderSide(3, THEME.border_light),
                top=None,
                right=ft.BorderSide(3, THEME.border_dark),
                bottom=ft.BorderSide(3, THEME.border_dark),
            ),
        )

        app_frame = ft.Column(
            [self._build_window_title_bar(), self._shell, bottom_bar],
            spacing=0,
            expand=True,
        )

        self.page.add(app_frame)

    def _on_tabs_reorder(self, tabs: list) -> None:
        """侧边栏标签页排序变更回调

        Args:
            tabs: 排序后的标签页列表
        """
        self._tab_defs = list(tabs)

    def _on_import_save(self) -> None:
        """侧边栏设置当前存档按钮回调"""
        try:
            path = self.pick_directory()
            if not path:
                return
            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self.warn_dialog("提示", "这不是有效存档目录，请选择包含 level.dat 的文件夹。")
                return
            self._set_current_save_context(context)
        except Exception as ex:
            self.error_dialog("错误", f"设置当前存档失败: {ex}")

    def _on_recent_save_select(self, path: str) -> None:
        try:
            context = CurrentSaveContext.from_path(path)
            if not context.is_valid:
                self.warn_dialog("提示", "该最近存档已失效，目录中未找到 level.dat。")
                self._recent_saves = [
                    s for s in self._recent_saves if s.get("path") != path]
                self._sidebar.set_recent_saves(self._recent_saves)
                self._save_recent_saves()
                return
            self._set_current_save_context(context)
        except Exception as ex:
            self.error_dialog("错误", f"设置当前存档失败: {ex}")

    def _set_current_save_context(self, context: CurrentSaveContext) -> None:
        self._current_save_context = context
        self._current_save_path = context.display_path
        self._sidebar.set_current_save_name(context.name, context.display_path)
        self._remember_recent_save(context)
        self._activate_explorer_with_current_save(context.display_path)
        if hasattr(self, "notification_manager") and self.notification_manager:
            self.notification_manager.show_success(
                f"当前存档已设置为 {context.name}，相关功能将自动使用该存档")

    def _activate_explorer_with_current_save(self, path: str) -> None:
        try:
            if "explorer" not in self.views:
                self.views["explorer"] = self._create_view("explorer")
            explorer_view = self.views["explorer"]
            if hasattr(explorer_view, "on_save_selected"):
                explorer_view.on_save_selected(path)
            if self._sidebar.selected_id != "explorer":
                self._sidebar.select_tab("explorer")
            else:
                self._content.content = explorer_view
                self._update_top_action("explorer", explorer_view)
                self.page.update()
        except Exception as ex:
            self.log(f"激活存档浏览器失败: {ex}", "ERROR")

    def _load_recent_saves(self) -> List[Dict[str, str]]:
        try:
            saves = self.config.config.get("recent_saves", [])
            if isinstance(saves, list):
                return [s for s in saves if isinstance(
                    s, dict) and s.get("path")][:5]
        except Exception:
            pass
        return []

    def _save_recent_saves(self) -> None:
        try:
            self.config.config["recent_saves"] = self._recent_saves[:5]
            self.config.save()
        except Exception as ex:
            self.log(f"保存最近存档失败: {ex}", "ERROR")

    def _remember_recent_save(self, context: CurrentSaveContext) -> None:
        save = {"path": context.display_path, "name": context.name}
        self._recent_saves = [
            s for s in self._recent_saves if s.get("path") != context.display_path]
        self._recent_saves.insert(0, save)
        self._recent_saves = self._recent_saves[:5]
        self._sidebar.set_recent_saves(self._recent_saves)
        self._save_recent_saves()

    def _notify_current_view_save_selected(self, path: str) -> None:
        """通知当前视图存档已选中

        Args:
            path: 存档路径
        """
        current_view = self.views.get(self._sidebar.selected_id)
        if current_view and hasattr(current_view, 'on_save_selected'):
            try:
                current_view.on_save_selected(path)
            except Exception as ex:
                self.log(f"通知视图失败: {ex}", "ERROR")

    def _build_window_title_bar(self) -> ft.Container:
        """构建自定义窗口标题栏"""
        title_content = ft.Row(
            [
                ft.Container(
                    content=ft.Text("⛏", size=16, color=THEME.mc_gold),
                    width=32,
                    height=28,
                    alignment=ft.alignment.Alignment(0, 0),
                    bgcolor=THEME.bg_secondary,
                    border=mc_border(2),
                ),
                ft.Text(
                    "MCSaveHelper  ▣ Minecraft Save Toolkit",
                    size=13,
                    color=THEME.text_primary,
                    weight=ft.FontWeight.BOLD,
                    font_family="monospace",
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        # WindowDragArea 负责系统级拖拽；GestureDetector 补齐部分 Windows/Flet
        # 组合下双击标题栏不触发最大化/还原的问题。
        title_drag_area = ft.WindowDragArea(
            ft.GestureDetector(
                content=title_content,
                on_double_tap=self._toggle_maximize_window,
            ),
            maximizable=True,
            expand=True,
        )
        return ft.Container(
            content=ft.Row(
                [
                    title_drag_area,
                    self._build_window_controls(),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=44,
            padding=ft.Padding(left=12, right=12, top=8, bottom=8),
            bgcolor=THEME.mc_wood,
            border=ft.Border(
                left=None,
                top=None,
                right=None,
                bottom=ft.BorderSide(3, THEME.mc_grass),
            ),
        )

    def _window_button(
        self,
        text: str,
        bgcolor: str,
        on_click: Callable[[ft.ControlEvent], None],
    ) -> ft.Container:
        """创建窗口控制按钮"""
        return ft.Container(
            content=ft.Text(
                text,
                size=14,
                color=THEME.text_primary,
                weight=ft.FontWeight.BOLD,
                font_family="monospace",
                text_align=ft.TextAlign.CENTER,
            ),
            width=32,
            height=28,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=bgcolor,
            border=mc_border(2),
            on_click=on_click,
            ink=True,
        )

    def _build_window_controls(self) -> ft.Row:
        """构建窗口控制按钮组"""
        self._maximize_window_button = self._window_button(
            "□", THEME.mc_stone, self._toggle_maximize_window)
        return ft.Row([self._window_button("—",
                                           THEME.mc_stone,
                                           self._minimize_window),
                       self._maximize_window_button,
                       self._window_button("×",
                                           THEME.mc_redstone,
                                           self._close_window),
                       ],
                      spacing=6,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER,
                      )

    def _minimize_window(self, e: ft.ControlEvent) -> None:
        self.page.window.minimized = True
        self.page.window.update()

    def _toggle_maximize_window(self, e: Any = None) -> None:
        """最大化/还原窗口。

        自定义标题栏隐藏了系统标题按钮，因此显式实现 Windows 常见行为：
        单击最大化按钮或双击标题栏都切换最大化状态。
        """
        try:
            if getattr(self.page.window, "minimized", False):
                self.page.window.minimized = False
            self.page.window.maximized = not bool(
                getattr(self.page.window, "maximized", False))
            self.page.window.update()
            self._sync_maximize_button_state()
        except Exception as ex:
            logger.error(f"切换窗口最大化失败: {ex}", module="App")

    def _sync_maximize_button_state(self) -> None:
        """同步最大化按钮显示，贴近 Windows 的最大化/还原语义。"""
        try:
            btn = getattr(self, "_maximize_window_button", None)
            if not btn or not isinstance(btn.content, ft.Text):
                return
            btn.content.value = "❐" if getattr(
                self.page.window, "maximized", False) else "□"
            btn.tooltip = "还原" if getattr(
                self.page.window, "maximized", False) else "最大化"
            btn.update()
        except Exception:
            pass

    def _close_window(self, e: ft.ControlEvent) -> None:
        """关闭窗口 - 清理资源后安全关闭"""
        self._shutdown_app()

    def _on_window_event(self, e) -> None:
        """处理系统窗口事件，确保标题栏关闭也执行清理。"""
        try:
            event_type = getattr(e, "type", None)
            if event_type == ft.WindowEventType.CLOSE or str(
                    event_type).lower().endswith("close"):
                self._shutdown_app()
            elif str(event_type).lower().endswith(("maximize", "unmaximize", "restore", "resize")):
                self._sync_maximize_button_state()
        except Exception:
            pass

    def _shutdown_app(self) -> None:
        """执行应用关闭流程。

        Flet 0.85+ 的 window.close()/destroy() 是异步方法，不能在同步点击回调中
        直接调用；统一通过 page.run_task 调度，并在必要时用进程级兜底避免残留。
        """
        if self._shutdown_started:
            return
        self._shutdown_started = True

        from app.ui.utils import set_app_closing

        # 1. 设置关闭标记，防止新的 UI 更新
        set_app_closing(True)

        # 2. 停止性能监控
        try:
            perf_monitor.disable()
            resource_monitor.stop()
        except Exception:
            pass

        # 3. 停止心跳线程
        try:
            self._heartbeat_active = False
        except Exception:
            pass

        # 4. 关闭日志，释放文件句柄并停止日志线程
        try:
            logger.shutdown()
        except Exception:
            pass

        # 5. 调度异步销毁窗口
        try:
            async def _destroy_window():
                try:
                    self.page.window.prevent_close = False
                    await self.page.window.destroy()
                except Exception:
                    try:
                        await self.page.window.close()
                    except Exception:
                        pass

            self.page.run_task(_destroy_window)
        except Exception:
            pass

        # 6. 兜底退出：如果 Flet 运行循环没有结束，避免进程留在后台
        try:
            import os
            import threading

            def _force_exit() -> None:
                os._exit(0)

            timer = threading.Timer(2.0, _force_exit)
            timer.daemon = True
            timer.start()
        except Exception:
            pass

    def _build_top_bar(self) -> ft.Container:
        """构建顶部栏"""
        return ft.Container(
            content=ft.Column(
                [
                    ft.Container(height=6, bgcolor=THEME.mc_grass),
                    ft.Container(
                        content=ft.Row(
                            [
                                ft.Row(
                                    [
                                        ft.Container(
                                            content=ft.Text("⛏", size=24, color=THEME.mc_gold),
                                            width=48,
                                            height=48,
                                            alignment=ft.alignment.Alignment(0, 0),
                                            bgcolor=THEME.bg_secondary,
                                            border=mc_border(),
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
                                            spacing=2,
                                        ),
                                    ],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Row(
                                    [self._top_actions],
                                    spacing=15,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        padding=ft.Padding(left=18, right=18, top=12, bottom=12),
                        bgcolor=THEME.mc_wood,
                    ),
                ],
                spacing=0,
            ),
            bgcolor=THEME.mc_wood,
            border=mc_border(3),
        )

    # ════════════════════════════════════════════
    #  视图切换
    # ════════════════════════════════════════════

    def _switch_view(self, view_id: str) -> None:
        """切换到指定视图

        Args:
            view_id: 视图ID
        """
        try:
            if view_id not in self.views:
                self.views[view_id] = self._create_view(view_id)
            current_view = self.views[view_id]
            self._content.content = current_view
            self._update_top_action(view_id, current_view)
            if self._current_save_path and hasattr(
                    current_view, 'on_save_selected'):
                try:
                    current_view.on_save_selected(self._current_save_path)
                except Exception as ex:
                    self.log(f"同步当前存档失败: {ex}", "ERROR")
            self.page.update()
        except Exception as e:
            traceback.print_exc()
            self.log(f"加载视图 '{view_id}' 失败: {e}", "ERROR")
            self._handle_view_error(view_id, e)

    def _update_top_action(
            self,
            view_id: str,
            current_view: ft.Control) -> None:
        actions = self._get_top_actions(view_id, current_view)
        self._top_actions.controls.clear()
        for action in actions:
            width = max(86, min(140, len(action.label) * 14 + 28))
            builder = btn_danger if action.style == "danger" else btn_primary
            self._top_actions.controls.append(
                builder(
                    action.label,
                    on_click=action.handler,
                    width=width,
                    height=38))
        self._top_actions.visible = bool(actions)

    def _get_top_actions(
            self,
            view_id: str,
            current_view: ft.Control) -> List[TopAction]:
        if view_id == "explorer":
            return [
                TopAction("开始统计", lambda e: current_view._analyze_world_stats(e)),
                TopAction("打开搜索", lambda e: current_view._start_entity_block_search(e)),
                TopAction("刷新区域图", lambda e: current_view._refresh_heatmap()),
                TopAction("暂存玩家", lambda e: current_view._stage_player_edit_form(e)),
                TopAction("提交变更", lambda e: current_view._commit_nbt_changes(e)),
                TopAction("丢弃暂存", lambda e: current_view._discard_nbt_changes(e), "danger"),
            ]
        action_map: Dict[str, TopAction] = {
            "migrator": TopAction("开始转换", lambda e: self.start()),
            "save_repair": TopAction("检测存档", lambda e: current_view._start_detect(e)),
            "map_export": TopAction("开始导出", lambda e: current_view._start_export(e)),
            "compare": TopAction("开始对比", lambda e: current_view._compare(e)),
            "mappings": TopAction("导入语言文件", lambda e: current_view._import_lang(e)),
            "server_properties": TopAction("读取配置", lambda e: current_view._load(e)),
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
            self._content.content = self._build_error_placeholder(
                view_id, error)
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
            self._content.content = ft.Container(
                content=ft.Text(
                    f"加载页面 '{view_id}' 时出错: {error}",
                    color=THEME.error, size=14,
                ),
                padding=40,
            )
            self.page.update()
        except Exception:
            pass

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
            return view_class(self)
        return ft.Container()

    def _build_error_placeholder(
            self,
            view_id: str,
            error: Exception) -> ft.Container:
        """视图加载失败时的错误占位页面 - 可复制、可关闭

        Args:
            view_id: 视图ID
            error: 异常对象

        Returns:
            ft.Container: 错误占位页容器
        """
        tb = traceback.format_exc()

        # 创建可选择的错误信息文本
        error_text = ft.SelectableText(
            str(error),
            size=13,
            color=THEME.text_secondary
        )

        # 创建可选择的堆栈跟踪文本
        traceback_text = ft.SelectableText(
            tb,
            size=11,
            color=THEME.text_muted,
            font_family="monospace"
        )

        # 关闭按钮
        close_btn = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_color=THEME.text_secondary,
            on_click=lambda e: self._close_error_view(),
            tooltip="关闭"
        )

        # 重试按钮
        retry_btn = ft.ElevatedButton(
            "🔄 重试",
            on_click=lambda e: self._retry_view(view_id),
            bgcolor=THEME.accent,
            color=THEME.text_primary,
        )

        # 返回按钮
        back_btn = ft.OutlinedButton(
            "← 返回首页",
            on_click=lambda e: self._switch_view("explorer"),
        )

        # 复制按钮
        copy_btn = ft.OutlinedButton(
            "📋 复制错误",
            on_click=lambda e: self._copy_error_to_clipboard(tb),
        )

        return ft.Container(
            content=ft.Column([
                # 标题行
                ft.Row([
                    ft.Icon(
                        ft.Icons.ERROR_OUTLINE,
                        size=48,
                        color=THEME.error),
                    ft.Column([
                        ft.Text(
                            f"加载页面 '{view_id}' 时出错",
                            size=18, color=THEME.text_primary, weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            "请检查错误信息，或尝试返回首页",
                            size=12, color=THEME.text_muted,
                        ),
                    ], spacing=4),
                    close_btn,
                ], spacing=16, alignment=ft.MainAxisAlignment.START),

                ft.Divider(height=20, color=THEME.border_subtle),

                # 错误信息
                ft.Text(
                    "错误信息：",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary),
                ft.Container(
                    content=error_text,
                    bgcolor=THEME.bg_secondary,
                    border_radius=8,
                    padding=10,
                    width=700,
                ),

                ft.Container(height=12),

                # 堆栈跟踪
                ft.Text(
                    "详细信息（可复制）：",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.text_secondary),
                ft.Container(
                    content=ft.Container(
                        content=traceback_text,
                        padding=10,
                    ),
                    bgcolor=THEME.bg_secondary,
                    border_radius=8,
                    width=700,
                    height=250,
                ),

                ft.Container(height=20),

                # 操作按钮
                ft.Row([
                    retry_btn,
                    back_btn,
                    copy_btn,
                ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=40,
            expand=True,
        )

    def _copy_error_to_clipboard(self, error_text: str) -> None:
        """复制错误信息到剪贴板

        Args:
            error_text: 要复制的错误文本
        """
        try:
            self.page.set_clipboard(error_text)
            self.info_dialog("✅ 成功", "错误信息已复制到剪贴板\n你可以直接粘贴到任何地方")
        except Exception as e:
            self.warn_dialog("复制失败", f"无法复制到剪贴板，请手动选择并复制错误信息\n\n错误：{str(e)}")

    def _close_error_view(self) -> None:
        """关闭错误页面，返回首页"""
        self.views.pop("error", None)
        self._switch_view("explorer")

    def _retry_view(self, view_id: str) -> None:
        """移除缓存的失败视图，重新尝试加载

        Args:
            view_id: 视图ID
        """
        self.views.pop(view_id, None)
        try:
            self._switch_view(view_id)
        except Exception:
            pass

    # ════════════════════════════════════════════
    #  日志
    # ════════════════════════════════════════════

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

    # ════════════════════════════════════════════
    #  进度
    # ════════════════════════════════════════════

    def update_progress(self, value: float) -> None:
        """更新进度条

        Args:
            value: 进度值（0.0 到 1.0）
        """
        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True

        # 使用新的进度条组件方法
        self._progress_bar.set_value(value)
        self._progress_label.value = self._t(
            "top_bar.progress", "进度 {percent}%",
            percent=int(value * 100),
        )
        self.page.update()

    def show_progress(self, task_name: str = "") -> None:
        """显示进度条

        Args:
            task_name: 任务名称（如"转换中"、"扫描中"等）
        """
        self._progress_container.visible = True
        if task_name:
            self._progress_label.value = task_name
        else:
            self._progress_label.value = "处理中..."
        self._progress_bar.set_value(0.0)
        self.page.update()

    def hide_progress(self) -> None:
        """隐藏进度条"""
        self._progress_container.visible = False
        self._progress_label.value = self._t("top_bar.ready", "就绪")
        self._progress_bar.set_value(0.0)
        self.page.update()

    def update_progress_with_task(self, task_name: str, value: float) -> None:
        """更新进度条（带任务名称）

        Args:
            task_name: 任务名称
            value: 进度值（0.0 到 1.0）
        """
        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True

        # 设置任务名称和进度
        if value >= 0 and value <= 1.0:
            self._progress_label.value = f"{task_name} {int(value * 100)}%"
        else:
            self._progress_label.value = task_name

        self._progress_bar.set_value(value)
        self.page.update()

    def set_progress_label(self, text: str) -> None:
        """设置进度标签文本

        Args:
            text: 标签文本
        """
        # 确保进度条可见
        if not self._progress_container.visible:
            self._progress_container.visible = True
        self._progress_label.value = text
        self.page.update()

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        # 使用新的进度条组件方法
        self._progress_bar.set_value(value)

    # ════════════════════════════════════════════
    #  对话框
    # ════════════════════════════════════════════

    def _close_dialog(self) -> None:
        """关闭当前打开的对话框"""
        if self._current_dialog:
            self._current_dialog.open = False
            self.page.update()
            self._current_dialog = None

    def _show_dialog(
            self,
            title: str,
            message: str,
            color: str = THEME.accent,
            include_details: bool = False,
            exception: Optional[Exception] = None) -> None:
        """显示对话框

        Args:
            title: 对话框标题
            message: 对话框消息
            color: 按钮颜色
            include_details: 是否包含异常详情
            exception: 异常对象
        """
        # 先关闭现有对话框
        self._close_dialog()

        # 构建内容
        content_list: List[ft.Control] = [
            ft.Text(message, color=THEME.text_secondary)]

        # 存储完整错误信息用于复制
        full_error_text = f"{title}\n\n{message}"

        if include_details and exception:
            error_details = traceback.format_exc()
            full_error_text += f"\n\n详细信息：\n{error_details}"

            # 可滚动的错误详情容器
            details_container = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "详细信息：",
                            size=12,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.text_primary),
                        ft.Container(
                            content=ft.Text(
                                error_details,
                                size=11,
                                color=THEME.text_muted,
                                selectable=True,
                            ),
                            bgcolor=THEME.bg_secondary,
                            padding=8,
                            border_radius=4,
                        ),
                    ],
                    spacing=6,
                    scroll=ft.ScrollMode.AUTO,
                ),
                padding=ft.Padding(
                    top=10,
                    right=0,
                    bottom=0,
                    left=0),
                height=200,
            )
            content_list.append(details_container)

        content = ft.Column(content_list, tight=True)

        # 创建对话框实例
        d = ft.AlertDialog(
            title=ft.Text(title, color=THEME.text_primary),
            content=content,
            actions=[],
        )

        # 定义关闭按钮的处理函数
        def handle_ok(e):
            d.open = False
            self.page.update()
            self._current_dialog = None

        # 定义复制按钮的处理函数
        def handle_copy(e):
            try:
                # 尝试使用 Flet 的 clipboard API
                if hasattr(self.page, 'set_clipboard'):
                    self.page.set_clipboard(full_error_text)
                else:
                    # 尝试使用 clipboard 属性
                    self.page.clipboard = full_error_text
                    self.page.update()

                # 显示复制成功提示
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text("错误信息已复制到剪贴板", color=THEME.text_primary),
                    bgcolor=THEME.mc_grass,
                    duration=2000,
                )
                self.page.snack_bar.open = True
                self.page.update()
            except Exception:
                # 如果复制失败，显示错误提示
                self.page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "复制失败，错误信息可手动选择复制",
                        color=THEME.text_primary),
                    bgcolor=THEME.warning,
                    duration=3000,
                )
                self.page.snack_bar.open = True
                self.page.update()

        # 添加按钮
        actions = []

        # 如果有错误详情，添加复制按钮
        if include_details and exception:
            actions.append(
                ft.TextButton(
                    "📋 复制错误信息",
                    style=ft.ButtonStyle(color=THEME.text_secondary),
                    on_click=handle_copy,
                )
            )

        actions.append(
            ft.TextButton(
                self._t("dialogs.ok", "确定"),
                style=ft.ButtonStyle(color=color),
                on_click=handle_ok,
            )
        )

        d.actions = actions

        self._current_dialog = d
        self.page.overlay.append(d)
        d.open = True
        self.page.update()

    def info_dialog(self, title: str, message: str) -> None:
        """显示信息对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self._show_dialog(title, message, THEME.accent)

    def warn_dialog(self, title: str, message: str) -> None:
        """显示警告对话框

        Args:
            title: 对话框标题
            message: 对话框消息
        """
        self._show_dialog(title, message, THEME.warning)

    def error_dialog(self, title: str, message: str,
                     exception: Optional[Exception] = None,
                     show_details: bool = False) -> None:
        """显示错误对话框，可以选择是否显示异常详情

        Args:
            title: 对话框标题
            message: 对话框消息
            exception: 异常对象
            show_details: 是否显示异常详情
        """
        self._show_dialog(
            title,
            message,
            THEME.error,
            include_details=show_details,
            exception=exception)

    def handle_exception(
            self,
            exception: Exception,
            title: Optional[str] = None,
            log: bool = True,
            show_dialog: bool = True) -> None:
        """统一异常处理方法

        Args:
            exception: 异常对象
            title: 对话框标题
            log: 是否记录日志
            show_dialog: 是否显示对话框
        """
        if title is None:
            title = self._t("dialogs.error", "错误")

        # 记录日志
        if log:
            logger.error(f"{title}: {str(exception)}", module="App")
            logger.error(traceback.format_exc(), module="App")

        # 显示对话框
        if show_dialog:
            self.error_dialog(
                title,
                str(exception),
                exception=exception,
                show_details=True)

    # ════════════════════════════════════════════
    #  文件选择
    # ════════════════════════════════════════════

    def pick_directory(self) -> Optional[str]:
        """选择目录对话框

        Returns:
            Optional[str]: 选择的目录路径，取消则返回None
        """
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory(
                title=self._t("common.select", "选择目录"))
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def pick_file(self, title: str = "",
                  file_types: Optional[List[tuple]] = None) -> Optional[str]:
        """选择文件对话框

        Args:
            title: 对话框标题
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径，取消则返回None
        """
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            ft_list = file_types or [
                (self._t("common.all_files", "所有文件"), "*.*")]
            d_title = title or self._t("common.select", "选择文件")
            path = filedialog.askopenfilename(title=d_title, filetypes=ft_list)
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def save_file(self, title: str = "", default_ext: str = ".txt",
                  file_types: Optional[List[tuple]] = None) -> Optional[str]:
        """保存文件对话框

        Args:
            title: 对话框标题
            default_ext: 默认扩展名
            file_types: 文件类型过滤

        Returns:
            Optional[str]: 选择的文件路径，取消则返回None
        """
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            ft_list = file_types or [
                (self._t("common.all_files", "所有文件"), "*.*")]
            d_title = title or self._t("common.save", "保存文件")
            path = filedialog.asksaveasfilename(
                title=d_title, defaultextension=default_ext,
                filetypes=ft_list,
            )
            root.destroy()
            return path if path else None
        except Exception:
            return None

    # ════════════════════════════════════════════
    #  迁移入口
    # ════════════════════════════════════════════

    def start(self) -> None:
        """开始转换按钮回调"""
        self.migration_controller.start()

    def _try_update_page(self) -> None:
        """尝试更新页面，忽略错误"""
        self.migration_controller.try_update_page()

    # ─── 公共 UI 控制方法（供控制器使用） ─────────
    def set_start_button_enabled(self, enabled: bool) -> None:
        """设置开始按钮的启用状态

        Args:
            enabled: 是否启用按钮
        """
        self._start_btn.disabled = not enabled

    def set_progress_label(self, text: str) -> None:
        """设置进度标签文本

        Args:
            text: 标签文本
        """
        self._progress_label.value = text

    def set_progress_value(self, value: float) -> None:
        """设置进度条值

        Args:
            value: 进度值 (0.0 - 1.0)
        """
        # 使用新的进度条组件方法
        self._progress_bar.set_value(value)

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

    # ════════════════════════════════════════════
    #  快捷操作
    # ════════════════════════════════════════════

    def open_folder(self, path: str) -> None:
        """在系统文件管理器中打开目录

        Args:
            path: 目录路径
        """
        self.migration_controller.open_folder(path)

    # ─── 文件选择快捷方法（供视图使用） ─────────

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
        if "migrator" in self.views:
            view = self.views["migrator"]
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
