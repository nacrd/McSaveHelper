"""MCSaveHelper Flet main application"""
import os
import re
import threading
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Optional, List, Dict, Callable

import flet as ft

from core.fast_mode import run_fast
from core.full_mode import run_full
from core.uuid_utils import get_offline_uuid_str, get_online_uuid
from core.config import config_manager
from core.batch_processor import BatchProcessor, scan_worlds_directory
from core.logger import LogLevel, logger, setup_default_logging
from core.i18n import init_translations, t
from core.types import LogCallback, ProgressCallback
from ui.constants import COLORS
from ui.sidebar import Sidebar
from ui.widgets import LogPanel, card, section_title, label, btn_primary, btn_ghost, btn_success, btn_danger
from ui.widgets import text_field, checkbox, UUIDMappingTable
from ui.views.migrator import MigratorView
from ui.views.explorer import ExplorerView
from ui.views.mappings import MappingsView
from ui.views.settings import SettingsView

init_translations()


def main(page: ft.Page):
    App(page)


class App:
    def __init__(self, page: ft.Page) -> None:
        self.page: ft.Page = page
        page.title = t("app.title", "MCSaveHelper · 存档管理工具")
        page.theme_mode = ft.ThemeMode.DARK
        page.bgcolor = COLORS["bg_primary"]
        page.padding = 0
        page.window.width = 1100
        page.window.height = 820
        page.window.min_width = 1000
        page.window.min_height = 720

        self._init_state()
        self._init_logging()
        self._build_ui()
        self._switch_view("migrator")
        page.update()

    def _init_state(self) -> None:
        self.mode: str = "fast"
        self.src_path: str = ""
        self.dest_path: str = os.getcwd()
        self.world_name: str = "world"
        self.offline_mode: bool = False
        self.clean_mode: bool = True
        self.pure_clean_mode: bool = False
        self.query_name: str = ""
        self.manual_names: str = ""
        self.batch_mode: bool = False
        self.batch_processor: Any = None
        self.batch_worlds: List[Path] = []
        self.version_detection: bool = config_manager.config.get("version_detection", True)
        self.max_concurrent: int = config_manager.config.get("batch_processing", {}).get("max_concurrent", 2)
        self.custom_uuid_mappings: Dict[str, str] = config_manager.config.get("custom_uuid_mappings", {}).copy()
        self.use_custom_mapping: bool = config_manager.config.get("use_custom_mapping", False)
        self.batch_dir_path: str = ""
        self.scan_result_text: str = ""

        self.log_panel: LogPanel = LogPanel()
        self._progress_bar: ft.ProgressBar = ft.ProgressBar(
            value=0, color=COLORS["accent"],
            bgcolor="rgba(255,255,255,0.05)",
            height=4, border_radius=2,
        )
        self._progress_label: ft.Text = ft.Text(
            t("top_bar.ready", "就绪"), size=12, color=COLORS["accent_light"],
            weight=ft.FontWeight.BOLD,
        )
        self._start_btn: ft.Button = btn_primary(t("top_bar.start_conversion", "开始转换"), width=140, height=40)
        self._start_btn.on_click = lambda e: self.start()
        self.views: Dict[str, Any] = {}
        self._content: ft.Container = ft.Container(
            padding=ft.padding.only(left=32, right=32, top=24, bottom=24),
        )
        self._content.expand = True

    def _init_logging(self):
        def ui_log_callback(message: str, tag: str):
            ts = time.strftime("%H:%M:%S")
            self.log_panel.log(f"[{ts}] [{tag.upper()}] {message}", tag.lower())

        setup_default_logging(
            enable_console=True, enable_file=True, file_path=None,
            enable_ui=True, ui_callback=ui_log_callback,
            level=LogLevel.INFO,
        )
        logger.info("MCSaveHelper 应用启动", module="App")

    def _show_dialog(self, title: str, message: str, color: str = COLORS["accent"]) -> None:
        d = ft.AlertDialog(
            title=ft.Text(title, color=COLORS["text_primary"]),
            content=ft.Text(message, color=COLORS["text_secondary"]),
            actions=[ft.TextButton(content=t("dialogs.ok", "确定"), style=ft.ButtonStyle(color=color))],
            open=True,
        )
        self.page.open(d)

    def _info_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, COLORS["accent"])

    def _warn_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, COLORS["warning"])

    def _error_dialog(self, title: str, message: str) -> None:
        self._show_dialog(title, message, COLORS["error"])

    def _build_ui(self):
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
        row = ft.Row([sidebar, body], spacing=0,
                     vertical_alignment=ft.CrossAxisAlignment.START)
        row.expand = True
        self.page.add(row)

    def _build_top_bar(self) -> ft.Container:
        progress_row = ft.Row([
            self._progress_label,
            self._progress_bar,
        ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        return ft.Container(
            content=ft.Row([
                ft.Row([
                    ft.Text("🌍", size=28, color=COLORS["accent_light"]),
                    ft.Text("MCSaveHelper", size=22, weight=ft.FontWeight.BOLD,
                            color=COLORS["text_primary"]),
                    ft.Text(t("app.subtitle", "存档管理工具"), size=11, color=COLORS["text_muted"]),
                ], spacing=10),
                ft.Row([progress_row, self._start_btn], spacing=15),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.only(left=25, right=25, top=15, bottom=15),
            bgcolor=COLORS["bg_secondary"],
        )

    def _switch_view(self, view_id: str):
        if view_id not in self.views:
            self.views[view_id] = self._create_view(view_id)
        self._content.content = self.views[view_id]
        self.page.update()

    def _create_view(self, view_id: str) -> ft.Control:
        if view_id == "migrator":
            return MigratorView(self)
        elif view_id == "explorer":
            return ExplorerView(self)
        elif view_id == "mappings":
            return MappingsView(self)
        elif view_id == "settings":
            return SettingsView(self)
        return ft.Container()

    def log_msg(self, msg: str, level: str = "INFO") -> None:
        log_level = LogLevel.from_string(level)
        logger.log(log_level, msg, module="App")

    def log_header(self, msg: str) -> None:
        self.log_panel.log(f"\n{'=' * 50}", "separator")
        self.log_panel.log(msg, "header")
        self.log_panel.log(f"{'=' * 50}", "separator")

    def update_progress(self, value: float) -> None:
        self._progress_bar.value = value
        self._progress_label.value = t("top_bar.progress", "进度 {percent}%", percent=int(value * 100))
        self.page.update()

    def clear_log(self) -> None:
        self.log_panel.clear()

    def _pick_directory(self) -> Optional[str]:
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory(title=t("common.select", "选择目录"))
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def _pick_file(self, title: str = "", file_types: Optional[List[tuple]] = None) -> Optional[str]:
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            ft_list = file_types or [(t("common.select", "所有文件"), "*.*")]
            dialog_title = title or t("common.select", "选择文件")
            path = filedialog.askopenfilename(title=dialog_title, filetypes=ft_list)
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def _save_file(self, title: str = "", default_ext: str = ".txt",
                   file_types: Optional[List[tuple]] = None) -> Optional[str]:
        try:
            from tkinter import Tk, filedialog
            root = Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            ft_list = file_types or [(t("common.select", "所有文件"), "*.*")]
            dialog_title = title or t("common.save", "保存文件")
            path = filedialog.asksaveasfilename(title=dialog_title, defaultextension=default_ext, filetypes=ft_list)
            root.destroy()
            return path if path else None
        except Exception:
            return None

    def choose_src(self, e: Optional[ft.ControlEvent] = None) -> None:
        p = self._pick_directory()
        if p:
            self.src_path = p
            self.page.update()

    def choose_dest(self, e: Optional[ft.ControlEvent] = None) -> None:
        p = self._pick_directory()
        if p:
            self.dest_path = p
            self.page.update()

    def choose_batch_dir(self, e: Optional[ft.ControlEvent] = None) -> None:
        p = self._pick_directory()
        if p:
            self.batch_dir_path = p
            self.page.update()

    def scan_batch_worlds(self) -> None:
        bd = self.batch_dir_path.strip()
        if not bd:
            self._warn_dialog(t("dialogs.warning", "提示"), t("messages.please_select_batch_dir", "请先选择批量存档目录"))
            return
        bp = Path(bd)
        if not bp.exists():
            self._error_dialog(t("dialogs.error", "错误"), t("messages.batch_dir_not_exist", "批量存档目录不存在"))
            return
        self.batch_worlds = scan_worlds_directory(bp)
        if self.batch_worlds:
            wn = ', '.join([w.name for w in self.batch_worlds[:3]])
            if len(self.batch_worlds) > 3:
                wn += '...'
            self.scan_result_text = t("messages.scanned_worlds", "扫描到 {count} 个世界存档: {names}",
                                      count=len(self.batch_worlds), names=wn)
            self.log_msg(t("messages.batch_scan_complete", "批量扫描完成: 找到 {count} 个世界存档",
                          count=len(self.batch_worlds)), "SUCCESS")
        else:
            self.scan_result_text = t("messages.no_valid_worlds", "未找到有效的世界存档（需要包含level.dat）")
            self.log_msg(t("messages.batch_scan_no_worlds", "批量扫描: 未找到有效的世界存档"), "WARN")

    def query_uuid(self) -> Optional[str]:
        name = self.query_name.strip()
        if not name:
            self._warn_dialog(t("dialogs.warning", "提示"), t("messages.enter_player_name", "请输入玩家名称"))
            return None
        if not re.match(r"^[A-Za-z0-9_]{3,16}$", name):
            self._warn_dialog(t("dialogs.warning", "提示"),
                              t("messages.invalid_player_name_format", "玩家名称格式不正确（3-16位字母数字或下划线）"))
            return None
        official_name: Optional[str] = None
        online_uuid: Optional[str] = None
        if not self.offline_mode:
            self.log_msg(t("messages.uuid_query_api", "正在查询玩家 {name} 的正版UUID...", name=name), "API")
            try:
                online_uuid, official_name = get_online_uuid(name, self.log_msg)
            except Exception as e:
                self.log_msg(t("messages.uuid_query_api_fail", "正版UUID查询失败: {error}", error=str(e)), "WARN")
        else:
            self.log_msg(t("messages.uuid_query_offline_skip", "强制离线模式，跳过正版UUID查询"), "INFO")
        display_name = official_name if official_name else name
        offline_uuid = get_offline_uuid_str(display_name)

        lines = [f"{t('right_panel.player_name', '玩家名')}: {name}"]
        if official_name and official_name != name:
            lines.append(f"{t('right_panel.official_name', '官方大小写')}: {official_name}  ⚠️")
        lines.append(f"{t('right_panel.offline_uuid', '离线 UUID')}: {offline_uuid}")
        lines.append(f"{t('right_panel.online_uuid', '正版 UUID')}: {online_uuid if online_uuid else '(' + t('right_panel.not_available', '未获取到') + ')'}")
        if official_name and official_name != name:
            lines.append("")
            lines.append(f"⚠️ {t('right_panel.offline_calc_hint', '离线服务器使用 {name} 计算 UUID', name=official_name)}")
        result = "\n".join(lines)
        self.log_msg(t("messages.uuid_query_result", "查询结果 -> 离线 UUID: {uuid}", uuid=offline_uuid), "INFO")
        if online_uuid:
            self.log_msg(t("messages.uuid_query_online_result", "查询结果 -> 正版 UUID: {uuid}", uuid=online_uuid), "INFO")
        return result

    def start(self) -> None:
        src = self.src_path.strip()
        dest = self.dest_path.strip()
        wn = self.world_name.strip()
        if not dest:
            dest = os.getcwd()
            self.dest_path = dest
        if self.batch_mode:
            if not self.batch_worlds:
                self._error_dialog(t("dialogs.error", "错误"),
                                   t("messages.scan_batch_dir_first", "请先扫描批量存档目录"))
                return
            self.clear_log()
            self._start_btn.disabled = True
            self.update_progress(0)
            self._progress_label.value = t("top_bar.preparing_batch", "正在准备批量处理...")
            self.page.update()
            threading.Thread(target=self.run_batch_task, args=(dest,), daemon=True).start()
            return
        if not src or not wn:
            self._error_dialog(t("dialogs.error", "错误"),
                               t("messages.fill_src_and_world_name", "请填写源目录和世界名称"))
            return
        sp = Path(src)
        dp = Path(dest)
        if not (sp / "level.dat").exists():
            self._error_dialog(t("dialogs.error", "错误"),
                               t("messages.invalid_source_archive", "源目录不是有效的Minecraft存档（缺少level.dat）"))
            return
        if not dp.exists():
            self._error_dialog(t("dialogs.error", "错误"),
                               t("messages.server_dir_not_exist", "目标目录不存在"))
            return
        self.clear_log()
        self._start_btn.disabled = True
        self.update_progress(0)
        self._progress_label.value = t("top_bar.preparing", "正在准备...")
        self.page.update()
        threading.Thread(target=self.run_task, args=(sp, dp, wn), daemon=True).start()

    def run_task(self, src_path: Path, dest_path: Path, world_name: str) -> None:
        try:
            self.log_header(t("messages.migration_started", "开始迁移任务"))
            version = config_manager.detect_minecraft_version(src_path)
            if version:
                self.log_msg(t("messages.version_detected", "检测到版本: {version}", version=version), "INFO")

            manual = [n.strip() for n in self.manual_names.split(",") if n.strip()]

            if self.mode == "fast":
                run_fast(src_path, dest_path, world_name, self.offline_mode, self.clean_mode,
                         self.pure_clean_mode, manual, self.log_msg)
            else:
                run_full(src_path, dest_path, world_name, self.offline_mode, self.clean_mode,
                         self.pure_clean_mode, manual, self.log_msg, self.update_progress)

            self.log_header(t("messages.migration_complete_header", "迁移完成"))
            self.log_msg(t("messages.migration_complete", "所有操作已成功完成！"), "SUCCESS")
            output_path = dest_path / world_name
            if output_path.exists():
                self.open_folder(str(output_path))
                self.log_msg(t("messages.opened_output_dir", "已打开输出目录: {path}", path=str(output_path)), "INFO")
            self._progress_label.value = t("top_bar.completed", "已完成")
            self._info_dialog(t("dialogs.success", "成功"),
                              t("messages.migration_success", "迁移完成！输出目录: {output_path}", output_path=str(output_path)))
        except Exception as e:
            self.log_msg(t("messages.migration_exception", "迁移失败: {error}", error=str(e)), "ERROR")
            import traceback
            traceback.print_exc()
            self._progress_label.value = t("top_bar.failed", "失败")
            self._error_dialog(t("dialogs.error", "错误"),
                               t("messages.migration_exception", "迁移失败: {error}", error=str(e)))
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self.page.update()

    def run_batch_task(self, dest_dir: str) -> None:
        try:
            self.log_header(t("messages.batch_migration_started", "开始批量处理"))
            dest_path = Path(dest_dir)
            self._save_config()
            manual = [n.strip() for n in self.manual_names.split(",") if n.strip()]
            self.batch_processor = BatchProcessor(int(self.max_concurrent))
            world_names = [f"world_{i+1}" for i in range(len(self.batch_worlds))]
            results = self.batch_processor.process_batch(
                self.batch_worlds, dest_path, world_names, self.mode,
                self.offline_mode, self.clean_mode, self.pure_clean_mode,
                manual, self.log_msg, self.update_progress,
            )
            success = sum(1 for r in results.values() if r["success"])
            self.log_header(t("messages.batch_migration_complete_header", "批量处理完成"))
            self.log_msg(t("messages.batch_migration_complete", "成功: {success}/{total}",
                          success=success, total=len(results)), "SUCCESS")
            self._progress_label.value = t("top_bar.batch_completed", "批量处理完成")
        except Exception as e:
            self.log_msg(t("messages.save_failed", "批量处理失败: {error}", error=str(e)), "ERROR")
            import traceback
            traceback.print_exc()
            self._progress_label.value = t("top_bar.batch_failed", "批量处理失败")
        finally:
            self._start_btn.disabled = False
            self._progress_bar.value = 0
            self.page.update()

    def open_folder(self, path: str) -> None:
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.log_msg(t("messages.cannot_open_folder", "无法打开文件夹: {error}", error=str(e)), "WARN")

    def _save_config(self) -> None:
        config_manager.config["version_detection"] = self.version_detection
        config_manager.config["batch_processing"]["max_concurrent"] = self.max_concurrent
        config_manager.config["custom_uuid_mappings"] = self.custom_uuid_mappings
        config_manager.config["use_custom_mapping"] = self.use_custom_mapping
        config_manager.save_config()

    def _on_uuid_mappings_change(self, mappings: Dict[str, str]) -> None:
        self.custom_uuid_mappings = mappings
        self._save_config()

    def _switch_to_mappings_view(self) -> None:
        self._switch_view("mappings")
