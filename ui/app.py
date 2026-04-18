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

# ------------------ 主题系统 ------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg_primary": "#0D1117",
    "bg_secondary": "#161B22",
    "bg_card": "#1E242C",
    "border": "#30363D",
    "accent": "#3B82F6",
    "accent_hover": "#2563EB",
    "success": "#2EA043",
    "warning": "#D29922",
    "error": "#F85149",
    "text_primary": "#E6EDF3",
    "text_secondary": "#8B949E",
    "text_muted": "#6E7681",
    "log_bg": "#0A0C10",
    "terminal_green": "#7EE787",
    "terminal_yellow": "#E3B341",
    "terminal_red": "#F47067",
    "terminal_blue": "#79C0FF",
}


class TerminalLikeTextbox(ctk.CTkTextbox):
    """自定义终端风格文本框，自动添加前缀和颜色标记"""
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            font=ctk.CTkFont(family="Cascadia Code", size=11),
            fg_color=COLORS["log_bg"],
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self._configure_tags()

    def _configure_tags(self):
        self.tag_config("info", foreground=COLORS["text_primary"])
        self.tag_config("success", foreground=COLORS["terminal_green"])
        self.tag_config("warn", foreground=COLORS["terminal_yellow"])
        self.tag_config("error", foreground=COLORS["terminal_red"])
        self.tag_config("api", foreground=COLORS["terminal_blue"])
        self.tag_config("timestamp", foreground=COLORS["text_muted"])


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MC Migrator Pro · 存档迁移工具")
        self.geometry("1050x780")
        self.minsize(950, 700)

        # 变量
        self.mode_var = ctk.StringVar(value="fast")
        self.src_path = ctk.StringVar()
        self.dest_path = ctk.StringVar()
        self.world_name = ctk.StringVar(value="world")
        self.offline_mode = ctk.BooleanVar(value=False)
        self.clean_mode = ctk.BooleanVar(value=True)
        self.query_name_var = ctk.StringVar()

        self.dest_path.set(os.getcwd())

        self.build_ui()

    def build_ui(self):
        # 主背景容器
        self.main_bg = ctk.CTkFrame(self, fg_color=COLORS["bg_primary"], corner_radius=0)
        self.main_bg.pack(fill="both", expand=True)

        # 顶部导航栏
        self._build_top_bar()

        # 核心内容区域
        content_frame = ctk.CTkFrame(self.main_bg, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=25, pady=15)

        # 左右两列容器
        self.left_panel = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))

        self.right_panel = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.right_panel.pack(side="left", fill="both", expand=True)

        # 构建左侧和右侧
        self._build_left_panel(self.left_panel)
        self._build_right_panel(self.right_panel)

    def _build_top_bar(self):
        top_frame = ctk.CTkFrame(
            self.main_bg, fg_color=COLORS["bg_secondary"], corner_radius=0, height=70
        )
        top_frame.pack(fill="x")

        title_label = ctk.CTkLabel(
            top_frame,
            text="🌍 Minecraft 存档迁移助手",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=COLORS["text_primary"],
        )
        title_label.pack(side="left", padx=25, pady=15)

        progress_container = ctk.CTkFrame(top_frame, fg_color="transparent")
        progress_container.pack(side="right", padx=25, pady=15)

        self.progress_label = ctk.CTkLabel(
            progress_container,
            text="就绪",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"]
        )
        self.progress_label.pack(side="left", padx=(0,10))

        self.progress = ctk.CTkProgressBar(
            progress_container, width=200, height=8, progress_color=COLORS["accent"]
        )
        self.progress.pack(side="left")
        self.progress.set(0)

        self.start_btn = ctk.CTkButton(
            top_frame,
            text="🚀 开始转换",
            height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self.start,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
        )
        self.start_btn.pack(side="right", padx=(0,25), pady=15)

    def _build_left_panel(self, parent):
        # 目录设置
        dir_card = self._create_card(parent)
        dir_card.pack(fill="x", pady=(0,15))
        self._add_section_title(dir_card, "📁 存档目录配置", icon_only=False)

        self._add_labeled_entry(
            dir_card, "客户端存档", self.src_path, "选择世界文件夹 (包含 level.dat)", self.choose_src
        )
        self._add_labeled_entry(
            dir_card, "服务端根目录", self.dest_path, "默认为程序当前目录", self.choose_dest
        )

        name_frame = ctk.CTkFrame(dir_card, fg_color="transparent")
        name_frame.pack(fill="x", padx=20, pady=(5,15))
        ctk.CTkLabel(
            name_frame,
            text="世界文件夹名",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w")
        ctk.CTkEntry(
            name_frame,
            textvariable=self.world_name,
            height=36,
            placeholder_text="例如: world",
            border_width=1,
            border_color=COLORS["border"]
        ).pack(fill="x", pady=(5,0))

        # 手动玩家名
        manual_card = self._create_card(parent)
        manual_card.pack(fill="x", pady=(0,15))
        self._add_section_title(manual_card, "👥 手动指定玩家 (选填)", icon_only=False)
        self.manual_names = ctk.CTkEntry(
            manual_card,
            height=38,
            placeholder_text="多个玩家用英文逗号分隔，例如: Steve, Alex",
            border_width=1,
            border_color=COLORS["border"]
        )
        self.manual_names.pack(fill="x", padx=20, pady=(5,15))

        # 日志区域
        log_header = ctk.CTkFrame(parent, fg_color="transparent")
        log_header.pack(fill="x", pady=(0,5))
        ctk.CTkLabel(
            log_header,
            text="📋 运行日志",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        ctk.CTkButton(
            log_header,
            text="🗑️ 清空",
            width=70,
            height=28,
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["border"],
            command=self.clear_log
        ).pack(side="right")

        self.log = TerminalLikeTextbox(parent, height=200)
        self.log.pack(fill="both", expand=True)

    def _build_right_panel(self, parent):
        # 模式选择
        mode_card = self._create_card(parent)
        mode_card.pack(fill="x", pady=(0,15))
        self._add_section_title(mode_card, "⚙️ 迁移模式", icon_only=False)
        mode_frame = ctk.CTkFrame(mode_card, fg_color="transparent")
        mode_frame.pack(fill="x", padx=20, pady=(10,5))
        ctk.CTkRadioButton(mode_frame, text="⚡ 快速模式", variable=self.mode_var, value="fast",
                           font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=(0,30))
        ctk.CTkRadioButton(mode_frame, text="🧠 完整模式", variable=self.mode_var, value="full",
                           font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        ctk.CTkLabel(mode_card, text="快速：仅复制双 UUID 文件   |   完整：深度转换 + 可选精简",
                     font=ctk.CTkFont(size=12), text_color=COLORS["text_muted"]).pack(anchor="w", padx=20, pady=(0,15))

        # UUID 查询
        uuid_card = self._create_card(parent)
        uuid_card.pack(fill="x", pady=(0,15))
        self._add_section_title(uuid_card, "🔍 UUID 查询", icon_only=False)
        query_frame = ctk.CTkFrame(uuid_card, fg_color="transparent")
        query_frame.pack(fill="x", padx=20, pady=(10,5))
        ctk.CTkEntry(query_frame, textvariable=self.query_name_var, height=36,
                     placeholder_text="输入玩家名，如: Steve", border_width=1, border_color=COLORS["border"]
                     ).pack(side="left", fill="x", expand=True, padx=(0,10))
        ctk.CTkButton(query_frame, text="🔎 查询", width=80, height=36,
                       command=self.query_uuid, fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"]
                       ).pack(side="right")
        self.query_result = TerminalLikeTextbox(uuid_card, height=100)
        self.query_result.pack(fill="x", padx=20, pady=(5,15))
        self._set_readonly_text(self.query_result, "💡 查询结果会显示在这里...\n离线 UUID 与 正版 UUID")

        # 附加选项
        opt_card = self._create_card(parent)
        opt_card.pack(fill="x")
        self._add_section_title(opt_card, "🔧 附加选项", icon_only=False)
        opt_frame = ctk.CTkFrame(opt_card, fg_color="transparent")
        opt_frame.pack(fill="x", padx=20, pady=(10,15))
        ctk.CTkCheckBox(opt_frame, text="强制离线模式 (不请求 Mojang API)", variable=self.offline_mode).pack(anchor="w", pady=5)
        ctk.CTkCheckBox(opt_frame, text="精简存档 (删除缓存/日志等)", variable=self.clean_mode).pack(anchor="w", pady=5)

    # ---------- 工具函数 ----------
    def _create_card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=12, fg_color=COLORS["bg_card"], border_width=1, border_color=COLORS["border"])

    def _add_section_title(self, parent, text, icon_only=False):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w", padx=20, pady=(15,5))

    def _add_labeled_entry(self, parent, label_text, var, placeholder, browse_cmd):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=5, padx=20)
        ctk.CTkLabel(frame, text=label_text, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=COLORS["text_secondary"]).pack(anchor="w")
        entry_frame = ctk.CTkFrame(frame, fg_color="transparent")
        entry_frame.pack(fill="x", pady=(5,0))
        ctk.CTkEntry(entry_frame, textvariable=var, height=36,
                     placeholder_text=placeholder, border_width=1, border_color=COLORS["border"]).pack(side="left", fill="x", expand=True, padx=(0,10))
        ctk.CTkButton(entry_frame, text="📂 浏览", width=90, height=36, command=browse_cmd,
                       fg_color=COLORS["bg_secondary"], hover_color=COLORS["border"]).pack(side="right")

    def _set_readonly_text(self, textbox, content):
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------- 功能方法 (线程安全已加固) ----------
    def choose_src(self):
        path = filedialog.askdirectory(title="选择客户端存档目录")
        if path:
            self.src_path.set(path)

    def choose_dest(self):
        path = filedialog.askdirectory(title="选择服务端根目录")
        if path:
            self.dest_path.set(path)

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

            self.log_msg("=" * 50, "SUCCESS")
            self.log_msg("迁移完成！", "SUCCESS")

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


if __name__ == "__main__":
    app = App()
    app.mainloop()