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
from pathlib import Path
from typing import Any, Optional, List, Dict, Callable

import flet as ft

from core.logger import LogLevel, logger, setup_default_logging
from core.i18n import init_translations
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

        # ─── 初始化服务 ─────────────────────────
        init_translations()
        self.i18n: I18nService = I18nService()
        self.config: ConfigService = ConfigService()
        self.migration: MigrationService = MigrationService(self.config)
        self.uuid: UUIDService = UUIDService()

        # ─── 同步配置到迁移参数 ─────────────────
        self._sync_config_to_migration()

        # ─── UI 组件 ────────────────────────────
        self.log_panel: LogPanel = LogPanel()
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
        self._switch_view("migrator")
        page.update()

    # ════════════════════════════════════════════
    #  初始化
    # ════════════════════════════════════════════

    def _t(self, key: str, default: str = "", **kwargs) -> str:
        """翻译快捷方法"""
        return self.i18n.translate(key, default, **kwargs)

    def _setup_page(self) -> None:
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
        mc = self.config.migration
        mc.version_detection = self.config.version_detection
        # 其他字段由视图直接设置

    # ════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════

    def _build_ui(self) -> None:
        sidebar = Sidebar(
            tabs=[
                {"id": "migrator", "label": "批量迁移", "icon": "📦"},
                {"id": "explorer", "label": "存档探险", "icon": "🗺️"},
                {"id": "mappings", "label": "映射管理", "icon": "🔗"},
                {"id": "settings", "label": "设置", "icon": "⚙️"},
            ],
            on_tab_select=self._switch_view,
            default_tab="migrator",
        )
        top_bar = self._build_top_bar()
        body = ft.Column([top_bar, self._content], spacing=0)
        body.expand = True
        row = ft.Row(
            [sidebar, body], spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        row.expand = True
        self.page.add(row)

    def _build_top_bar(self) -> ft.Container:
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
        if view_id not in self.views:
            self.views[view_id] = self._create_view(view_id)
        self._content.content = self.views[view_id]
        self.page.update()

    def _create_view(self, view_id: str) -> ft.Control:
        # 延迟导入视图模块，避免循环依赖
        from app.ui.views.migrator import MigratorView
        from app.ui.views.explorer import ExplorerView
        from app.ui.views.mappings import MappingsView
        from app.ui.views.settings import SettingsView

        if view_id == "migrator":
            return MigratorView(self)
        elif view_id == "explorer":
            return ExplorerView(self)
        elif view_id == "mappings":
            return MappingsView(self)
        elif view_id == "settings":
            return SettingsView(self)
        return ft.Container()

    # ════════════════════════════════════════════
    #  日志
    # ════════════════════════════════════════════

    def log(self, msg: str, level: str = "INFO") -> None:
        log_level = LogLevel.from_string(level)
        logger.log(log_level, msg, module="App")

    def log_header(self, msg: str) -> None:
        self.log_panel.log(f"\n{'=' * 50}", "separator")
        self.log_panel.log(msg, "header")
        self.log_panel.log(f"{'=' * 50}", "separator")

    def clear_log(self) -> None:
        self.log_panel.clear()

    # ════════════════════════════════════════════
    #  进度
    # ════════════════════════════════════════════

    def update_progress(self, value: float) -> None:
        self._progress_bar.value = value
        self._progress_label.value = self._t(
            "top_bar.progress", "进度 {percent}%",
            percent=int(value * 100),
        )
        self.page.update()

    # ════════════════════════════════════════════
    #  对话框
    # ════════════════════════════════════════════

    def _show_dialog(self, title: str, message: str, color: str = THEME.accent) -> None:
        d = ft.AlertDialog(
            title=ft.Text(title, color=THEME.text_primary),
            content=ft.Text(message, color=THEME.text_secondary),
            actions=[
                ft.TextButton(
                    content=self._t("dialogs.ok", "确定"),
                    style=ft.ButtonStyle(color=color),
                )
            ],
            open=True,
        )
        self.page.overlay.append(d)
        self.page.update()

    def info_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, THEME.accent)

    def warn_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, THEME.warning)

    def error_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, THEME.error)

    # ════════════════════════════════════════════
    #  文件选择
    # ════════════════════════════════════════════

    def pick_directory(self) -> Optional[str]:
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

    def _save_config(self) -> None:
        c = self.config
        mc = c.migration
        c._config["version_detection"] = mc.version_detection
        c._config["batch_processing"]["max_concurrent"] = c.max_concurrent
        c._config["custom_uuid_mappings"] = c.custom_uuid_mappings
        c._config["use_custom_mapping"] = c.use_custom_mapping
        c.save()

    def _run_single_thread(self, dest_dir: str) -> None:
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
            self.log(self._t("messages.migration_exception", "迁移失败: {error}", error=str(e)), "ERROR")
            import traceback
            traceback.print_exc()
            self._progress_label.value = self._t("top_bar.failed", "失败")
            self.error_dialog(
                self._t("dialogs.error", "错误"),
                self._t("messages.migration_exception", "迁移失败: {error}", error=str(e)),
            )
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self.page.update()

    def _run_batch_thread(self, dest_dir: str) -> None:
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
            self.log(self._t("messages.save_failed", "批量处理失败: {error}", error=str(e)), "ERROR")
            import traceback
            traceback.print_exc()
            self._progress_label.value = self._t("top_bar.batch_failed", "批量处理失败")
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self.page.update()

    # ════════════════════════════════════════════
    #  快捷操作
    # ════════════════════════════════════════════

    def open_folder(self, path: str) -> None:
        self.migration.open_folder(path)

    # ─── 文件选择快捷方法（供视图使用）───────────

    def set_src(self) -> None:
        path = self.pick_directory()
        if path:
            self.config.migration.src_path = path
            self.page.update()

    def set_dest(self) -> None:
        path = self.pick_directory()
        if path:
            self.config.migration.dest_path = path
            self.page.update()

    def set_batch_dir(self) -> None:
        path = self.pick_directory()
        if path:
            self.config.migration.batch_dir_path = path
            self.page.update()

    def _on_uuid_mappings_change(self, mappings: Dict[str, str]) -> None:
        self.config.custom_uuid_mappings = mappings
        self._save_config()
