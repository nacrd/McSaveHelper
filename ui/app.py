"""MC Migrator Pro - Minecraft存档迁移工具

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


# ------------------ 主题系统 ------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class App(CommonUIMixin, TopBarMixin, LeftPanelMixin, RightPanelMixin, ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MC Migrator Pro · 存档迁移工具")
        self.geometry("1100x820")
        self.minsize(1000, 720)

        # 初始化变量
        self._initialize_variables()
        
        # 初始化组件
        self._initialize_components()
        
        # 构建UI
        self.build_ui()

    def _initialize_variables(self):
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

    def _initialize_components(self):
        """初始化组件变量"""
        # 批量处理相关
        self.batch_dir_path = ctk.StringVar()
        
        # UUID映射相关
        self.new_player_name = ctk.StringVar()
        self.new_uuid = ctk.StringVar()

    def build_ui(self):
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





    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- 功能方法 ----------
    def choose_src(self):
        path = filedialog.askdirectory(title="选择客户端存档目录")
        if path:
            self.src_path.set(path)

    def choose_dest(self):
        path = filedialog.askdirectory(title="选择服务端根目录")
        if path:
            self.dest_path.set(path)
    
    def choose_batch_dir(self):
        """选择批量存档目录"""
        path = filedialog.askdirectory(title="选择包含多个世界存档的目录")
        if path:
            self.batch_dir_path.set(path)
    
    def scan_batch_worlds(self):
        """扫描批量存档目录"""
        batch_dir = self.batch_dir_path.get().strip()
        if not batch_dir:
            messagebox.showwarning("提示", "请先选择批量存档目录")
            return
        
        batch_path = Path(batch_dir)
        if not batch_path.exists():
            messagebox.showerror("错误", "批量存档目录不存在")
            return
        
        self.batch_worlds = scan_worlds_directory(batch_path)
        
        if self.batch_worlds:
            self.batch_result_label.configure(
                text=f"扫描到 {len(self.batch_worlds)} 个世界存档: {', '.join([w.name for w in self.batch_worlds[:3]])}{'...' if len(self.batch_worlds) > 3 else ''}",
                text_color=COLORS["terminal_green"]
            )
            self.log_msg(f"批量扫描完成: 找到 {len(self.batch_worlds)} 个世界存档", "SUCCESS")
        else:
            self.batch_result_label.configure(
                text="未找到有效的世界存档（需要包含level.dat）",
                text_color=COLORS["terminal_red"]
            )
            self.log_msg("批量扫描: 未找到有效的世界存档", "WARN")

    def log_msg(self, msg, level="INFO"):
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

    def log_header(self, msg):
        """记录标题行"""
        def _write():
            self.log.configure(state="normal")
            self.log.insert("end", f"\n{'=' * 50}\n", "separator")
            self.log.insert("end", f"{msg}\n", "header")
            self.log.insert("end", f"{'=' * 50}\n", "separator")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.after(0, _write)

    def update_progress(self, value):
        """线程安全的进度更新 (附带百分比显示)"""
        def _update():
            self.progress.set(value)
            percent = int(value * 100)
            self.progress_label.configure(text=f"进度 {percent}%")
        self.after(0, _update)

    def query_uuid(self):
        name = self.query_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入玩家名")
            return
        if not re.match(r"^[A-Za-z0-9_]{3,16}$", name):
            messagebox.showwarning("提示", "玩家名格式不正确 (3-16个字符，仅字母数字下划线)")
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

    def start(self):
        src = self.src_path.get().strip()
        dest = self.dest_path.get().strip()
        world_name = self.world_name.get().strip()

        if not dest:
            dest = os.getcwd()
            self.dest_path.set(dest)

        # 批量处理模式
        if self.batch_mode.get():
            if not self.batch_worlds:
                messagebox.showerror("错误", "请先扫描批量存档目录")
                return
            
            self.clear_log()
            self.start_btn.configure(state="disabled")
            self.update_progress(0)
            self.progress_label.configure(text="准备批量处理...")
            
            threading.Thread(
                target=self.run_batch_task, args=(dest,), daemon=True
            ).start()
            return

        # 单文件处理模式
        if not src or not world_name:
            messagebox.showerror("错误", "请填写源存档路径和世界文件夹名")
            return

        src_path = Path(src)
        dest_path = Path(dest)

        if not (src_path / "level.dat").exists():
            messagebox.showerror("错误", "源存档无效，必须包含 level.dat")
            return
        if not dest_path.exists():
            messagebox.showerror("错误", "服务端目录不存在")
            return

        self.clear_log()
        self.start_btn.configure(state="disabled")
        self.update_progress(0)
        self.progress_label.configure(text="准备中...")

        threading.Thread(
            target=self.run_task, args=(src_path, dest_path, world_name), daemon=True
        ).start()

    def run_task(self, src_path, dest_path, world_name):
        try:
            self.log_header("开始迁移任务")
            
            # 检测版本
            version = config_manager.detect_minecraft_version(src_path)
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
                    src_path,
                    dest_path,
                    world_name,
                    offline,
                    clean,
                    manual,
                    self.log_msg,
                )
            else:
                run_full(
                    src_path,
                    dest_path,
                    world_name,
                    offline,
                    clean,
                    manual,
                    self.log_msg,
                    self.update_progress,
                )

            self.log_header("迁移完成")
            self.log_msg("所有操作已成功完成！", "SUCCESS")

            output_path = dest_path / world_name
            if output_path.exists():
                self.after(0, lambda: self.open_folder(output_path))
                self.log_msg(f"已打开输出目录: {output_path}", "INFO")

            self.after(
                0,
                lambda: messagebox.showinfo(
                    "完成", f"迁移成功！\n输出目录：{output_path}"
                ),
            )
            self.after(0, lambda: self.progress_label.configure(text="完成"))

        except Exception as e:
            self.log_msg(f"发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            self.after(
                0,
                lambda: messagebox.showerror(
                    "错误", f"迁移过程中发生异常:\n{str(e)}"
                ),
            )
            self.after(0, lambda: self.progress_label.configure(text="失败"))
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.progress.set(0))

    def run_batch_task(self, dest_dir: str):
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
            
            self.batch_processor = BatchProcessor(self.max_concurrent.get())
            
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
            
            self.after(0, lambda: self.progress_label.configure(text="批量处理完成"))
            
        except Exception as e:
            self.log_msg(f"批量处理发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self.progress_label.configure(text="批量处理失败"))
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.after(0, lambda: self.progress.set(0))

    def open_folder(self, path):
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
    
    def _toggle_batch_mode(self):
        """切换批量处理模式"""
        if self.batch_mode.get():
            self.batch_frame.pack(fill="x", padx=20, pady=(5,0))
        else:
            self.batch_frame.pack_forget()
    
    def _save_config(self):
        """保存配置"""
        config_manager.config["version_detection"] = self.version_detection.get()
        config_manager.config["batch_processing"]["max_concurrent"] = self.max_concurrent.get()
        config_manager.config["custom_uuid_mappings"] = self.custom_uuid_mappings
        config_manager.save_config()
    
    def _add_uuid_mapping(self):
        """添加自定义UUID映射"""
        player_name = self.new_player_name.get().strip()
        uuid = self.new_uuid.get().strip()
        
        if not player_name or not uuid:
            messagebox.showwarning("提示", "请填写玩家名和UUID")
            return
        
        # 验证UUID格式
        if not re.match(r'^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$', uuid):
            messagebox.showwarning("提示", "UUID格式不正确")
            return
        
        self.custom_uuid_mappings[player_name] = uuid
        self._save_config()
        self._update_uuid_list()
        
        self.new_player_name.set("")
        self.new_uuid.set("")
        
        self.log_msg(f"已添加自定义UUID映射: {player_name} -> {uuid}", "SUCCESS")
    
    def _update_uuid_list(self):
        """更新UUID映射列表显示"""
        self.uuid_listbox.configure(state="normal")
        self.uuid_listbox.delete("1.0", "end")
        
        if self.custom_uuid_mappings:
            for player_name, uuid in self.custom_uuid_mappings.items():
                self.uuid_listbox.insert("end", f"{player_name} -> {uuid}\n")
        else:
            self.uuid_listbox.insert("end", "暂无自定义UUID映射\n")
        
        self.uuid_listbox.configure(state="disabled")
    
    def _clear_uuid_mappings(self):
        """清空所有UUID映射"""
        if messagebox.askyesno("确认", "确定要清空所有自定义UUID映射吗？"):
            self.custom_uuid_mappings.clear()
            self._save_config()
            self._update_uuid_list()
            self.log_msg("已清空所有自定义UUID映射", "INFO")


if __name__ == "__main__":
    app = App()
    app.mainloop()