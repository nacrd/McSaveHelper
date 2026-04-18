"""Minecraft存档转换工具

主要功能：
- 将Minecraft客户端存档转换为服务端兼容格式
- 支持快速模式和完整模式
- 提供批量处理功能
- 支持自定义UUID映射
- 集成版本检测
"""
import os
import platform
import subprocess
import threading
import time
import re
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Optional, List, Tuple

import customtkinter as ctk

from core.fast_mode import run_fast
from core.full_mode import run_full
from core.uuid_utils import get_offline_uuid_str, get_online_uuid
from core.config import config_manager
from core.batch_processor import BatchProcessor, scan_worlds_directory
from ui.constants import COLORS
from ui.widgets import TerminalLikeTextbox
from ui.mixins.common import CommonUIMixin
from ui.mixins.top_bar import TopBarMixin
from ui.mixins.left_panel import LeftPanelMixin
from ui.mixins.right_panel import RightPanelMixin
from core.types import LogCallback, ProgressCallback
from core.i18n import init_translations, t


# ------------------ 主题系统 ------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# 初始化翻译系统
init_translations()

class App(CommonUIMixin, TopBarMixin, LeftPanelMixin, RightPanelMixin, ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(t("app.title", "MC Migrator Pro · 存档迁移工具"))
        self.geometry("1100x820")
        self.minsize(1000, 720)

        # 初始化变量
        self._initialize_variables()
        
        # 初始化组件
        self._initialize_components()
        
        # 构建UI
        self.build_ui()

    def _initialize_variables(self) -> None:
        """初始化应用变量"""
        self.mode_var = ctk.StringVar(value="fast")
        self.src_path = ctk.StringVar()
        self.dest_path = ctk.StringVar()
        self.world_name = ctk.StringVar(value="world")
        self.offline_mode = ctk.BooleanVar(value=False)
        self.clean_mode = ctk.BooleanVar(value=True)
        self.query_name_var = ctk.StringVar()
        self.manual_names = ctk.StringVar()
        
        # 批量处理相关
        self.batch_mode = ctk.BooleanVar(value=False)
        self.batch_processor = None
        self.batch_worlds = []
        
        # 高级配置
        self.version_detection = ctk.BooleanVar(value=config_manager.config["version_detection"])
        self.max_concurrent = ctk.IntVar(value=config_manager.config["batch_processing"]["max_concurrent"])
        
        # UUID映射管理
        self.custom_uuid_mappings = config_manager.config["custom_uuid_mappings"].copy()
        
        # 设置默认值
        self.dest_path.set(os.getcwd())

    def _initialize_components(self) -> None:
        """初始化组件变量"""
        # 批量处理相关
        self.batch_dir_path = ctk.StringVar()
        
        # UUID映射相关
        self.new_player_name = ctk.StringVar()
        self.new_uuid = ctk.StringVar()

    def build_ui(self) -> None:
        """构建现代化用户界面"""
        # 主背景容器
        self.main_bg = ctk.CTkFrame(self, fg_color=COLORS["bg_primary"], corner_radius=0)
        self.main_bg.pack(fill="both", expand=True)

        # 顶部导航栏
        self._build_top_bar()

        # 核心内容区域
        content_frame = ctk.CTkFrame(self.main_bg, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=30, pady=20)

        # 左右两列容器
        self.left_panel = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 18))

        self.right_panel = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.right_panel.pack(side="left", fill="both", expand=True)

        # 构建左侧和右侧
        self._build_left_panel(self.left_panel)
        self._build_right_panel(self.right_panel)


    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- 功能方法 ----------
    def choose_src(self) -> None:
        path = filedialog.askdirectory(title=t("dialogs.select_client_archive", "选择客户端存档目录"))
        if path:
            self.src_path.set(path)

    def choose_dest(self) -> None:
        path = filedialog.askdirectory(title=t("dialogs.select_server_root", "选择服务端根目录"))
        if path:
            self.dest_path.set(path)
    
    def choose_batch_dir(self) -> None:
        """选择批量存档目录"""
        path = filedialog.askdirectory(title=t("dialogs.select_batch_dir", "选择包含多个世界存档的目录"))
        if path:
            self.batch_dir_path.set(path)
    
    def scan_batch_worlds(self) -> None:
        """扫描批量存档目录"""
        batch_dir = self.batch_dir_path.get().strip()
        if not batch_dir:
            messagebox.showwarning(t("dialogs.warning", "提示"), t("messages.please_select_batch_dir", "请先选择批量存档目录"))
            return
        
        batch_path = Path(batch_dir)
        if not batch_path.exists():
            messagebox.showerror(t("dialogs.error", "错误"), t("messages.batch_dir_not_exist", "批量存档目录不存在"))
            return
        
        self.batch_worlds = scan_worlds_directory(batch_path)
        
        if self.batch_worlds:
            world_names = ', '.join([w.name for w in self.batch_worlds[:3]])
            if len(self.batch_worlds) > 3:
                world_names += '...'
            self.batch_result_label.configure(
                text=t("messages.scanned_worlds", "扫描到 {count} 个世界存档: {names}").format(
                    count=len(self.batch_worlds),
                    names=world_names
                ),
                text_color=COLORS["terminal_green"]
            )
            self.log_msg(
                t("messages.batch_scan_complete", "批量扫描完成: 找到 {count} 个世界存档").format(count=len(self.batch_worlds)),
                "SUCCESS"
            )
        else:
            self.batch_result_label.configure(
                text=t("messages.no_valid_worlds", "未找到有效的世界存档（需要包含level.dat）"),
                text_color=COLORS["terminal_red"]
            )
            self.log_msg(t("messages.batch_scan_no_worlds", "批量扫描: 未找到有效的世界存档"), "WARN")

    def log_msg(self, msg: str, level: str = "INFO") -> None:
        """线程安全的日志写入 (支持终端彩色标签)"""
        tag_map = {
            "INFO": "info",
            "SUCCESS": "success",
            "WARN": "warn",
            "ERROR": "error",
            "API": "api",
        }
        tag = tag_map.get(level, "info")

        def _write():
            timestamp = time.strftime("%H:%M:%S")
            self.log.configure(state="normal")
            self.log.insert("end", f"[{timestamp}] ", "timestamp")
            self.log.insert("end", f"[{level}] ", tag)
            self.log.insert("end", f"{msg}\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")

        self.after(0, _write)

    def log_header(self, msg: str) -> None:
        """记录标题行"""
        def _write():
            self.log.configure(state="normal")
            self.log.insert("end", f"\n{'=' * 50}\n", "separator")
            self.log.insert("end", f"{msg}\n", "header")
            self.log.insert("end", f"{'=' * 50}\n", "separator")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _write)

    def update_progress(self, value: float) -> None:
        """线程安全的进度更新 (附带百分比显示)"""
        def _update():
            self.progress.set(value)
            percent = int(value * 100)
            self.progress_label.configure(text=f"进度 {percent}%")
        self.after(0, _update)

    def query_uuid(self) -> None:
        name = self.query_name_var.get().strip()
        if not name:
            messagebox.showwarning(t("dialogs.warning"), t("messages.enter_player_name"))
            return
        if not re.match(r"^[A-Za-z0-9_]{3,16}$", name):
            messagebox.showwarning(t("dialogs.warning"), t("messages.invalid_player_name_format"))
            return

        official_name = None
        online_uuid = None

        if not self.offline_mode.get():
            self.log_msg(f"正在查询玩家 {name} 的正版UUID...", "API")
            try:
                online_uuid, official_name = get_online_uuid(name, self.log_msg)
            except Exception as e:
                self.log_msg(f"正版UUID查询失败: {e}", "WARN")
        else:
            self.log_msg("强制离线模式，跳过正版UUID查询", "INFO")

        display_name = official_name if official_name else name
        offline_uuid = get_offline_uuid_str(display_name)

        # 构建结果文本
        lines = []
        lines.append(f"玩家名: {name}")
        if official_name and official_name != name:
            lines.append(f"官方大小写: {official_name}  ⚠️")
        lines.append(f"离线 UUID: {offline_uuid}")
        lines.append(f"正版 UUID: {online_uuid if online_uuid else '(未获取到)'}")
        if official_name and official_name != name:
            lines.append("")
            lines.append(f"⚠️ 离线服务器使用 \"{official_name}\" 计算 UUID")

        self._set_readonly_text(self.query_result, "\n".join(lines))
        self.log_msg(f"查询结果 -> 离线 UUID: {offline_uuid} (基于: {display_name})", "INFO")
        if online_uuid:
            self.log_msg(f"查询结果 -> 正版 UUID: {online_uuid}", "INFO")

    def start(self) -> None:
        src = self.src_path.get().strip()
        dest = self.dest_path.get().strip()
        world_name = self.world_name.get().strip()

        if not dest:
            dest = os.getcwd()
            self.dest_path.set(dest)

        # 批量处理模式
        if self.batch_mode.get():
            if not self.batch_worlds:
                messagebox.showerror(t("dialogs.error"), t("messages.scan_batch_dir_first"))
                return
            
            self.clear_log()
            self.start_btn.configure(state="disabled")
            self.update_progress(0)
            self.progress_label.configure(text=t("messages.preparing_batch"))
            
            threading.Thread(
                target=self.run_batch_task, args=(dest,), daemon=True
            ).start()
            return

        # 单文件处理模式
        if not src or not world_name:
            messagebox.showerror(t("dialogs.error"), t("messages.fill_src_and_world_name"))
            return

        src_path = Path(src)
        dest_path = Path(dest)

        if not (src_path / "level.dat").exists():
            messagebox.showerror(t("dialogs.error"), t("messages.invalid_source_archive"))
            return
        if not dest_path.exists():
            messagebox.showerror(t("dialogs.error"), t("messages.server_dir_not_exist"))
            return

        self.clear_log()
        self.start_btn.configure(state="disabled")
        self.update_progress(0)
        self.progress_label.configure(text=t("messages.preparing"))

        threading.Thread(
            target=self.run_task, args=(src_path, dest_path, world_name), daemon=True
        ).start()

    def run_task(self, src_path: str, dest_path: str, world_name: str) -> None:
        try:
            self.log_header("开始迁移任务")
            
            # 检测版本
            version = config_manager.detect_minecraft_version(Path(src_path))
            if version:
                self.log_msg(f"检测到版本: {version}", "INFO")

            mode = self.mode_var.get()
            offline = self.offline_mode.get()
            clean = self.clean_mode.get()
            manual = [
                n.strip()
                for n in self.manual_names.get().split(",")
                if n.strip()
            ]

            if mode == "fast":
                run_fast(
                    Path(src_path),
                    Path(dest_path),
                    world_name,
                    offline,
                    clean,
                    manual,
                    self.log_msg,
                )
            else:
                run_full(
                    Path(src_path),
                    Path(dest_path),
                    world_name,
                    offline,
                    clean,
                    manual,
                    self.log_msg,
                    self.update_progress,
                )

            self.log_header("迁移完成")
            self.log_msg("所有操作已成功完成！", "SUCCESS")

            output_path = Path(dest_path) / world_name
            if output_path.exists():
                self.after(0, lambda: self.open_folder(str(output_path)))
                self.log_msg(f"已打开输出目录: {output_path}", "INFO")

            self.after(
                0,
                lambda: messagebox.showinfo(
                    t("dialogs.success"), t("messages.migration_success").format(output_path=output_path)
                ),
            )
            self.after(0, lambda: self.progress_label.configure(text=t("messages.completed")))

        except Exception as e:
            self.log_msg(f"发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            self.after(
                0,
                lambda: messagebox.showerror(
                    t("dialogs.error"), t("messages.migration_exception").format(error=str(e))
                ),
            )
            self.after(0, lambda: self.progress_label.configure(text=t("messages.failed")))
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.progress.set(0))

    def run_batch_task(self, dest_dir: str) -> None:
        """批量处理任务"""
        try:
            self.log_header("开始批量处理")
            
            dest_path = Path(dest_dir)
            
            # 更新配置
            self._save_config()
            
            mode = self.mode_var.get()
            offline = self.offline_mode.get()
            clean = self.clean_mode.get()
            manual = [
                n.strip()
                for n in self.manual_names.get().split(",")
                if n.strip()
            ]
            
            self.batch_processor = BatchProcessor(int(self.max_concurrent.get()))
            
            # 生成世界名称列表
            world_names = [f"world_{i+1}" for i in range(len(self.batch_worlds))]
            
            results = self.batch_processor.process_batch(
                self.batch_worlds,
                dest_path,
                world_names,
                mode,
                offline,
                clean,
                manual,
                self.log_msg,
                self.update_progress
            )
            
            # 显示结果统计
            success_count = sum(1 for r in results.values() if r["success"])
            total_count = len(results)
            
            self.log_header("批量处理完成")
            self.log_msg(f"成功: {success_count}/{total_count}", "SUCCESS")
            
            self.after(0, lambda: self.progress_label.configure(text=t("messages.batch_completed")))
            
        except Exception as e:
            self.log_msg(f"批量处理发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self.progress_label.configure(text=t("messages.batch_failed")))
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.progress.set(0))

    def open_folder(self, path: str) -> None:
        try:
            path_str = str(path)
            if platform.system() == "Windows":
                os.startfile(path_str)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path_str])
            else:
                subprocess.Popen(["xdg-open", path_str])
        except Exception as e:
            self.log_msg(f"无法打开文件夹: {e}", "WARN")
    
    def _toggle_batch_mode(self) -> None:
        """切换批量处理模式"""
        if self.batch_mode.get():
            self.batch_frame.pack(fill="x", padx=20, pady=(5,0))
        else:
            self.batch_frame.pack_forget()
    
    def _save_config(self) -> None:
        """保存配置"""
        config_manager.config["version_detection"] = self.version_detection.get()
        config_manager.config["batch_processing"]["max_concurrent"] = self.max_concurrent.get()
        config_manager.config["custom_uuid_mappings"] = self.custom_uuid_mappings
        config_manager.save_config()
    
    def _add_uuid_mapping(self) -> None:
        """添加自定义UUID映射"""
        player_name = self.new_player_name.get().strip()
        uuid = self.new_uuid.get().strip()
        
        if not player_name or not uuid:
            messagebox.showwarning(t("dialogs.warning"), t("messages.fill_player_name_and_uuid"))
            return
        
        # 验证UUID格式
        if not re.match(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$', uuid):
            messagebox.showwarning(t("dialogs.warning"), t("messages.invalid_uuid_format"))
            return
        
        self.custom_uuid_mappings[player_name] = uuid
        self._save_config()
        self._update_uuid_list()
        
        self.new_player_name.set("")
        self.new_uuid.set("")
        
        self.log_msg(f"已添加自定义UUID映射: {player_name} -> {uuid}", "SUCCESS")
    
    def _update_uuid_list(self) -> None:
        """更新UUID映射列表显示"""
        self.uuid_listbox.configure(state="normal")
        self.uuid_listbox.delete("1.0", "end")
        
        if self.custom_uuid_mappings:
            for player_name, uuid in self.custom_uuid_mappings.items():
                self.uuid_listbox.insert("end", f"{player_name} -> {uuid}\n")
        else:
            self.uuid_listbox.insert("end", "暂无自定义UUID映射\n")
        
        self.uuid_listbox.configure(state="disabled")
    
    def update_all_ui_texts(self) -> None:
        """更新所有UI文本（语言切换时调用）"""
        # 更新应用程序标题
        self.title(t("app.title", "Minecraft 存档转换工具"))
        
        # 调用各个混入类的UI更新方法
        if hasattr(self, '_update_ui_texts'):
            self._update_ui_texts()  # TopBarMixin的方法
        
        # 注意：LeftPanelMixin和RightPanelMixin的文本在构建时已经使用t()函数
        # 所以它们不需要动态更新，因为t()函数会实时返回当前语言的文本
        # 但是静态构建的文本需要重新配置
        
        # 记录日志
        self.log_msg(f"UI文本已更新为: {t('app.title')}", "INFO")
    
    def _clear_uuid_mappings(self) -> None:
        """清空所有UUID映射"""
        if messagebox.askyesno(t("common.confirm", "确认"), t("messages.confirm_clear_all_mappings")):
            self.custom_uuid_mappings.clear()
            self._save_config()
            self._update_uuid_list()
            self.log_msg("已清空所有自定义UUID映射", "INFO")


if __name__ == "__main__":
    app = App()
    app.mainloop()