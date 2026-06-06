"""Application Core —— 应用主协调器

替代原 ui/app.py 中的 App 类。职责：
  - 初始化所有服务（配置、UUID、迁移、国际化）
  - 管理 UI 全局状态（迁移参数、日志、进度）
  - 协调视图切换
  - 提供文件选择对话框
"""
import os
import re
import threading
import platform
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Optional, List, Dict, Callable

import flet as ft

from core.logger import LogLevel, logger, setup_default_logging
from core.types import LogCallback, ProgressCallback

from app.models.config import MigrationConfig
from app.services.config_service import ConfigService
from app.services.uuid_service import UUIDService
from app.services.migration_service import MigrationService
from app.services.i18n_service import I18nService

from app.ui.theme import THEME
from app.ui.sidebar import Sidebar
from app.ui.components.buttons import btn_primary, btn_ghost, btn_success, btn_danger
from app.ui.components.fields import text_field, checkbox, label
from app.ui.components.cards import card, section_title
from app.ui.components.log_panel import LogPanel
from app.ui.components.uuid_table import UUIDMappingTable


class Application:
    """MCSaveHelper 应用核心"""

    def __init__(self, page: ft.Page) -> None:
        self.page: ft.Page = page
        self._current_dialog: Optional[ft.AlertDialog] = None

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

        try:
            self.migration: MigrationService = MigrationService(self.config)
        except Exception as e:
            print(f"[WARN] MigrationService 初始化失败: {e}")
            self.migration = MigrationService.__new__(MigrationService)  # type: ignore

        try:
            self.uuid: UUIDService = UUIDService()
        except Exception as e:
            print(f"[WARN] UUIDService 初始化失败: {e}")
            self.uuid = UUIDService.__new__(UUIDService)  # type: ignore

        # ─── 同步配置到迁移参数 ─────────────────
        self._sync_config_to_migration()

        # ─── UI 组件 ────────────────────────────
        self.log_panel: LogPanel = LogPanel(
            title=self._t("log_panel.title", "日志"),
        )
        self._progress_bar: ft.ProgressBar = ft.ProgressBar(
            value=0, color=THEME.accent,
            bgcolor="rgba(255,255,255,0.05)",
            height=4, border_radius=2,
        )
        self._progress_label: ft.Text = ft.Text(
            self._t("top_bar.ready", "就绪"), size=12,
            color=THEME.accent_light, weight=ft.FontWeight.BOLD,
        )
        self._start_btn: ft.Button = btn_primary(
            self._t("top_bar.start_conversion", "开始转换"),
            width=140, height=40,
        )
        self._start_btn.on_click = lambda e: self.start()

        # ─── 视图容器 ───────────────────────────
        self.views: Dict[str, ft.Control] = {}
        self._content: ft.Container = ft.Container(
            padding=ft.Padding(left=32, right=32, top=24, bottom=24),
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
        page.padding = 0
        page.window.width = 1100
        page.window.height = 820
        page.window.min_width = 1000
        page.window.min_height = 720

    def _init_logging(self) -> None:
        """初始化日志系统"""
        def ui_log_callback(message: str, tag: str) -> None:
            ts = time.strftime("%H:%M:%S")
            self.log_panel.log(f"[{ts}] [{tag.upper()}] {message}", tag.lower())

        setup_default_logging(
            enable_console=True, enable_file=True, file_path=None,
            enable_ui=True, ui_callback=ui_log_callback,
            level=LogLevel.INFO,
        )
        logger.info("MCSaveHelper 应用启动", module="App")

    def _sync_config_to_migration(self) -> None:
        """同步配置到迁移参数"""
        mc = self.config.migration
        mc.version_detection = self.config.version_detection
        # 其他字段由视图直接设置

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════

    def _build_ui(self) -> None:
        """构建应用主界面"""
        # 标签页定义（存档探险为默认第一项）
        self._tab_defs = [
            {"id": "explorer", "label": self._t("sidebar.explorer", "存档探险"), "icon": "🗺️"},
            {"id": "migrator", "label": self._t("sidebar.migrator", "批量迁移"), "icon": "📦"},
            {"id": "mappings", "label": self._t("sidebar.mappings", "映射管理"), "icon": "🔗"},
            {"id": "settings", "label": self._t("sidebar.settings", "设置"), "icon": "⚙️"},
        ]
        self._sidebar = Sidebar(
            tabs=self._tab_defs,
            on_tab_select=self._switch_view,
            on_tabs_reorder=self._on_tabs_reorder,
            default_tab="explorer",
        )
        top_bar = self._build_top_bar()

        # 内容区域（上方）+ 日志面板（下方）
        content_area = ft.Column([top_bar, self._content], spacing=0)
        content_area.expand = True

        # 右侧：内容区 + 底部日志面板
        right_panel = ft.Column(
            [content_area, self.log_panel],
            spacing=0,
            expand=True,
        )

        row = ft.Row(
            [self._sidebar, right_panel], spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        row.expand = True
        self.page.add(row)

    def _on_tabs_reorder(self, tabs: list) -> None:
        """侧边栏标签页排序变更回调
        
        Args:
            tabs: 排序后的标签页列表
        """
        self._tab_defs = list(tabs)

    def _build_top_bar(self) -> ft.Container:
        """构建顶部栏
        
        Returns:
            ft.Container: 顶部栏容器
        """
        progress_row = ft.Row(
            [self._progress_label, self._progress_bar],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        return ft.Container(
            content=ft.Row(
                [
                    ft.Row(
                        [
                            ft.Text("🌍", size=28, color=THEME.accent_light),
                            ft.Text(
                                "MCSaveHelper", size=22,
                                weight=ft.FontWeight.BOLD,
                                color=THEME.text_primary,
                            ),
                            ft.Text(
                                self._t("app.subtitle", "存档管理工具"),
                                size=11, color=THEME.text_muted,
                            ),
                        ],
                        spacing=10,
                    ),
                    ft.Row([progress_row, self._start_btn], spacing=15),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            padding=ft.Padding(left=25, right=25, top=15, bottom=15),
            bgcolor=THEME.bg_secondary,
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
            self._content.content = self.views[view_id]
            self.page.update()
        except Exception as e:
            traceback.print_exc()
            self.log(f"加载视图 '{view_id}' 失败: {e}", "ERROR")
            self._handle_view_error(view_id, e)

    def _handle_view_error(self, view_id: str, error: Exception) -> None:
        """处理视图加载错误
        
        Args:
            view_id: 视图ID
            error: 异常对象
        """
        try:
            self._content.content = self._build_error_placeholder(view_id, error)
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

        view_map = {
            "migrator": MigratorView,
            "explorer": ExplorerView,
            "mappings": MappingsView,
            "settings": SettingsView,
        }
        
        view_class = view_map.get(view_id)
        if view_class:
            return view_class(self)
        return ft.Container()

    def _build_error_placeholder(self, view_id: str, error: Exception) -> ft.Container:
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
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=48, color=THEME.error),
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
                ft.Text("错误信息：", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_secondary),
                ft.Container(
                    content=error_text,
                    bgcolor=THEME.bg_secondary,
                    border_radius=8,
                    padding=10,
                    width=700,
                ),
                
                ft.Container(height=12),
                
                # 堆栈跟踪
                ft.Text("详细信息（可复制）：", size=12, weight=ft.FontWeight.BOLD, color=THEME.text_secondary),
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
        self.log_panel.log(f"\n{'=' * 50}", "separator")
        self.log_panel.log(msg, "header")
        self.log_panel.log(f"{'=' * 50}", "separator")

    def clear_log(self) -> None:
        """清空日志面板"""
        self.log_panel.clear()

    # ════════════════════════════════════════════
    #  进度
    # ════════════════════════════════════════════

    def update_progress(self, value: float) -> None:
        """更新进度条
        
        Args:
            value: 进度值（0.0 到 1.0）
        """
        self._progress_bar.value = value
        self._progress_label.value = self._t(
            "top_bar.progress", "进度 {percent}%",
            percent=int(value * 100),
        )
        self.page.update()

    # ════════════════════════════════════════════
    #  对话框
    # ════════════════════════════════════════════

    def _close_dialog(self) -> None:
        """关闭当前打开的对话框"""
        if self._current_dialog:
            self._current_dialog.open = False
            try:
                if self._current_dialog in self.page.overlay:
                    self.page.overlay.remove(self._current_dialog)
            except ValueError:
                pass  # 对话框可能已经不在 overlay 中了
            self.page.update()
            self._current_dialog = None

    def _show_dialog(self, title: str, message: str, color: str = THEME.accent,
                    include_details: bool = False, exception: Optional[Exception] = None) -> None:
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
        content_list: List[ft.Control] = [ft.Text(message, color=THEME.text_secondary)]
        
        if include_details and exception:
            error_details = traceback.format_exc()
            content_list.append(
                ft.Container(
                    content=ft.Text(error_details, size=11, color=THEME.text_muted),
                    padding=ft.Padding(top=10, right=0, bottom=0, left=0),
                )
            )
        
        content = ft.Column(content_list, tight=True)
        
        d = ft.AlertDialog(
            title=ft.Text(title, color=THEME.text_primary),
            content=content,
            actions=[
                ft.TextButton(
                    content=self._t("dialogs.ok", "确定"),
                    style=ft.ButtonStyle(color=color),
                    on_click=lambda e: self._close_dialog(),
                )
            ],
            open=True,
        )
        self._current_dialog = d
        self.page.overlay.append(d)
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
        self._show_dialog(title, message, THEME.error, include_details=show_details, exception=exception)
        
    def handle_exception(self, exception: Exception, title: Optional[str] = None, 
                        log: bool = True, show_dialog: bool = True) -> None:
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
            self.error_dialog(title, str(exception), exception=exception, show_details=True)

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
            path = filedialog.askdirectory(title=self._t("common.select", "选择目录"))
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def pick_file(self, title: str = "", file_types: Optional[List[tuple]] = None) -> Optional[str]:
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
            ft_list = file_types or [(self._t("common.all_files", "所有文件"), "*.*")]
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
            ft_list = file_types or [(self._t("common.all_files", "所有文件"), "*.*")]
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
        try:
            mc = self.config.migration

            if not mc.src_path and not mc.batch_mode:
                self.warn_dialog(
                    self._t("dialogs.warning", "提示"),
                    self._t("messages.please_select_source", "请先选择客户端存档目录"),
                )
                return

            self._start_btn.disabled = True
            self.page.update()

            # 保存配置
            self._save_config()

            dest_dir = mc.dest_path or os.getcwd()

            if mc.batch_mode and self.migration.batch_worlds:
                threading.Thread(
                    target=self._run_batch_thread,
                    args=(dest_dir,), daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=self._run_single_thread,
                    args=(dest_dir,), daemon=True,
                ).start()
        except Exception as e:
            self.handle_exception(e, title="启动转换失败")
            self._start_btn.disabled = False
            self._try_update_page()

    def _try_update_page(self) -> None:
        """尝试更新页面，忽略错误"""
        try:
            self.page.update()
        except Exception:
            pass

    def _save_config(self) -> None:
        """保存当前配置"""
        c = self.config
        mc = c.migration
        c._config["version_detection"] = mc.version_detection
        c._config["batch_processing"]["max_concurrent"] = c.max_concurrent
        c._config["custom_uuid_mappings"] = c.custom_uuid_mappings
        c._config["use_custom_mapping"] = c.use_custom_mapping
        c.save()

    def _run_single_thread(self, dest_dir: str) -> None:
        """执行单存档迁移的线程函数
        
        Args:
            dest_dir: 目标目录
        """
        mc = self.config.migration
        try:
            self.log_header(self._t("messages.migration_started", "开始迁移任务"))
            output_path = self.migration.run_single(
                src=mc.src_path,
                dest=dest_dir,
                world_name=mc.world_name,
                mode=mc.mode,
                offline=mc.offline_mode,
                clean=mc.clean_mode,
                pure_clean=mc.pure_clean_mode,
                manual_names_str=mc.manual_names,
                log_cb=self.log,
                progress_cb=self.update_progress,
            )
            self.log_header(self._t("messages.migration_complete", "迁移完成"))
            self.log(self._t("messages.migration_success", "迁移完成！输出目录: {output_path}",
                             output_path=output_path), "SUCCESS")
            self._progress_label.value = self._t("top_bar.completed", "已完成")
            self.info_dialog(
                self._t("dialogs.success", "成功"),
                self._t("messages.migration_success", "迁移完成！输出目录: {output_path}",
                        output_path=output_path),
            )
        except Exception as e:
            self.handle_exception(
                e,
                title=self._t("messages.migration_exception", "迁移失败: {error}", error=str(e)),
                log=True,
                show_dialog=False  # 我们将在下面自定义显示对话框
            )
            self._progress_label.value = self._t("top_bar.failed", "失败")
            self.error_dialog(
                self._t("dialogs.error", "错误"),
                self._t("messages.migration_exception", "迁移失败: {error}", error=str(e)),
                exception=e,
                show_details=True
            )
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self._try_update_page()

    def _run_batch_thread(self, dest_dir: str) -> None:
        """执行批量迁移的线程函数
        
        Args:
            dest_dir: 目标目录
        """
        mc = self.config.migration
        try:
            self.log_header(self._t("messages.batch_migration_started", "开始批量处理"))
            self._save_config()
            results = self.migration.run_batch(
                dest_dir=dest_dir,
                mode=mc.mode,
                offline=mc.offline_mode,
                clean=mc.clean_mode,
                pure_clean=mc.pure_clean_mode,
                manual_names_str=mc.manual_names,
                max_concurrent=self.config.max_concurrent,
                log_cb=self.log,
                progress_cb=self.update_progress,
            )
            success = sum(1 for r in results.values() if r["success"])
            self.log_header(self._t("messages.batch_migration_complete_header", "批量处理完成"))
            self.log(self._t("messages.batch_migration_complete",
                             "成功: {success}/{total}",
                             success=success, total=len(results)), "SUCCESS")
            self._progress_label.value = self._t("top_bar.batch_completed", "批量处理完成")
        except Exception as e:
            self.handle_exception(
                e,
                title=self._t("messages.save_failed", "批量处理失败: {error}", error=str(e)),
                log=True,
                show_dialog=False
            )
            self._progress_label.value = self._t("top_bar.batch_failed", "批量处理失败")
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self._try_update_page()

    # ════════════════════════════════════════════
    #  快捷操作
    # ════════════════════════════════════════════

    def open_folder(self, path: str) -> None:
        """在系统文件管理器中打开目录
        
        Args:
            path: 目录路径
        """
        self.migration.open_folder(path)

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
