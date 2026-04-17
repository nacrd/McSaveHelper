import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.fast_mode import run_fast
from core.full_mode import run_full
from core.uuid_utils import get_offline_uuid_str, get_online_uuid

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("MC Migrator Pro")
        self.geometry("950x750")
        self.minsize(800, 600)

        self.mode_var = ctk.StringVar(value="fast")
        self.src_path = ctk.StringVar()
        self.dest_path = ctk.StringVar()
        self.world_name = ctk.StringVar(value="world")
        self.offline_mode = ctk.BooleanVar(value=False)
        self.clean_mode = ctk.BooleanVar(value=True)

        self.dest_path.set(os.getcwd())

        self.build_ui()

    def build_ui(self):
        main_frame = ctk.CTkFrame(self, corner_radius=10)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # 标题
        ctk.CTkLabel(main_frame, text="Minecraft 存档助手",
                     font=("Arial", 24, "bold")).pack(pady=10)

        # 模式选择
        mode_frame = ctk.CTkFrame(main_frame)
        mode_frame.pack(pady=10)
        ctk.CTkRadioButton(mode_frame, text="⚡ 快速模式 (仅双UUID副本)",
                           variable=self.mode_var, value="fast",
                           font=("Arial", 14)).pack(side="left", padx=20)
        ctk.CTkRadioButton(mode_frame, text="🧠 完整模式 (深度UUID转换+精简)",
                           variable=self.mode_var, value="full",
                           font=("Arial", 14)).pack(side="left", padx=20)

        # 源存档选择
        ctk.CTkLabel(main_frame, text="客户端存档目录 (saves/世界名)",
                     font=("Arial", 12)).pack(anchor="w", pady=(15,0))
        src_frame = ctk.CTkFrame(main_frame)
        src_frame.pack(fill="x", pady=5)
        ctk.CTkEntry(src_frame, textvariable=self.src_path,
                     height=35).pack(side="left", fill="x", expand=True, padx=(0,10))
        ctk.CTkButton(src_frame, text="浏览", width=80,
                      command=self.choose_src).pack(side="right")

        # 目标服务器目录
        ctk.CTkLabel(main_frame, text="服务端根目录 (默认为当前目录)",
                     font=("Arial", 12)).pack(anchor="w", pady=(15,0))
        dest_frame = ctk.CTkFrame(main_frame)
        dest_frame.pack(fill="x", pady=5)
        ctk.CTkEntry(dest_frame, textvariable=self.dest_path,
                     height=35).pack(side="left", fill="x", expand=True, padx=(0,10))
        ctk.CTkButton(dest_frame, text="浏览", width=80,
                      command=self.choose_dest).pack(side="right")

        # 世界文件夹名
        ctk.CTkLabel(main_frame, text="服务端世界文件夹名",
                     font=("Arial", 12)).pack(anchor="w", pady=(15,0))
        ctk.CTkEntry(main_frame, textvariable=self.world_name,
                     width=250, height=35).pack(anchor="w", pady=5)

        # 选项
        opt_frame = ctk.CTkFrame(main_frame)
        opt_frame.pack(fill="x", pady=15)
        ctk.CTkCheckBox(opt_frame, text="强制离线模式 (不请求Mojang API)",
                        variable=self.offline_mode).pack(side="left", padx=15)
        ctk.CTkCheckBox(opt_frame, text="精简存档 (删除缓存/日志)",
                        variable=self.clean_mode).pack(side="left", padx=15)

        # --- 新增：UUID 查询区域 ---
        query_frame = ctk.CTkFrame(main_frame)
        query_frame.pack(fill="x", pady=15)

        ctk.CTkLabel(query_frame, text="🔍 UUID 查询 (输入玩家名)",
                     font=("Arial", 12, "bold")).pack(anchor="w", padx=10, pady=(10,5))

        input_frame = ctk.CTkFrame(query_frame)
        input_frame.pack(fill="x", padx=10, pady=5)
        self.query_name_var = ctk.StringVar()
        ctk.CTkEntry(input_frame, textvariable=self.query_name_var,
                     placeholder_text="例如: Steve", height=35).pack(side="left", fill="x", expand=True, padx=(0,10))
        ctk.CTkButton(input_frame, text="查询", width=80,
                      command=self.query_uuid).pack(side="right")

        self.query_result = ctk.CTkTextbox(query_frame, height=60, font=("Consolas", 11))
        self.query_result.pack(fill="x", padx=10, pady=(5,10))
        self.query_result.insert("1.0", "查询结果将显示在这里...")
        self.query_result.configure(state="disabled")
        # ------------------------

        # 手动玩家名
        ctk.CTkLabel(main_frame, text="手动指定玩家名 (选填，逗号分隔)",
                     font=("Arial", 12)).pack(anchor="w", pady=(15,0))
        self.manual_names = ctk.CTkEntry(main_frame, placeholder_text="例如: Steve, Alex",
                                         height=35)
        self.manual_names.pack(fill="x", pady=5)

        # 进度条
        self.progress = ctk.CTkProgressBar(main_frame)
        self.progress.pack(fill="x", pady=15)
        self.progress.set(0)

        # 日志框
        self.log = ctk.CTkTextbox(main_frame, height=200,
                                  font=("Consolas", 11))
        self.log.pack(fill="both", expand=True, pady=(0,10))

        # 开始转换按钮
        self.start_btn = ctk.CTkButton(main_frame, text="🚀 开始转换",
                                       height=45, font=("Arial", 14, "bold"),
                                       command=self.start)
        self.start_btn.pack(pady=10)

    # --- 新增：查询 UUID 的方法 ---
    def query_uuid(self):
        name = self.query_name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入玩家名")
            return

        # 默认使用用户输入的名字计算离线UUID
        official_name = None
        online_uuid = None

        if not self.offline_mode.get():
            self.log_msg(f"正在查询玩家 {name} 的正版UUID...", "API")
            online_uuid, official_name = get_online_uuid(name, self.log_msg)
        else:
            self.log_msg("强制离线模式，跳过正版UUID查询", "INFO")

        # 确定用于计算离线UUID的基准名称（优先官方大小写）
        display_name = official_name if official_name else name
        offline_uuid = get_offline_uuid_str(display_name)

        # 更新结果文本框
        self.query_result.configure(state="normal")
        self.query_result.delete("1.0", "end")
        result_text = f"玩家名: {name}"
        if official_name and official_name != name:
            result_text += f" (官方大小写: {official_name})"
        result_text += f"\n离线 UUID: {offline_uuid}"
        if official_name and official_name != name:
            result_text += f"   ⚠️ 基于官方名称计算"
        result_text += f"\n正版 UUID: {online_uuid if online_uuid else '(未获取到)'}"

        # 警告：如果用户输入大小写与官方不符
        if official_name and official_name != name:
            result_text += f"\n\n⚠️ 警告：您输入的大小写与官方记录不符！\n离线服务器使用 \"{official_name}\" 计算 UUID。"

        self.query_result.insert("1.0", result_text)
        self.query_result.configure(state="disabled")

        # 记录日志
        self.log_msg(f"查询结果 -> 离线 UUID: {offline_uuid} (基于: {display_name})", "INFO")
        if online_uuid:
            self.log_msg(f"查询结果 -> 正版 UUID: {online_uuid}", "INFO")

    def choose_src(self):
        path = filedialog.askdirectory(title="选择客户端存档目录")
        if path:
            self.src_path.set(path)

    def choose_dest(self):
        path = filedialog.askdirectory(title="选择服务端根目录")
        if path:
            self.dest_path.set(path)

    def log_msg(self, msg, level="INFO"):
        timestamp = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{timestamp}] [{level}] {msg}\n")
        self.log.see("end")
        self.update_idletasks()

    def update_progress(self, value):
        self.progress.set(value)
        self.update_idletasks()

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

        self.log.delete("1.0", "end")
        self.start_btn.configure(state="disabled")
        self.progress.set(0)

        threading.Thread(target=self.run_task,
                         args=(src_path, dest_path, world_name),
                         daemon=True).start()

    def run_task(self, src_path, dest_path, world_name):
        try:
            mode = self.mode_var.get()
            offline = self.offline_mode.get()
            clean = self.clean_mode.get()
            manual = [n.strip() for n in self.manual_names.get().split(',') if n.strip()]

            if mode == "fast":
                run_fast(src_path, dest_path, world_name, offline, clean, manual,
                         self.log_msg, self.update_progress)
            else:
                run_full(src_path, dest_path, world_name, offline, clean, manual,
                         self.log_msg, self.update_progress)

            self.log_msg("=" * 50, "SUCCESS")
            self.log_msg("迁移完成！", "SUCCESS")

            output_path = dest_path / world_name
            if output_path.exists():
                self.open_folder(output_path)
                self.log_msg(f"已打开输出目录: {output_path}", "INFO")

            self.after(0, lambda: messagebox.showinfo("完成", f"迁移成功！\n输出目录：{output_path}"))

        except Exception as e:
            self.log_msg(f"发生错误: {e}", "ERROR")
            import traceback
            traceback.print_exc()
        finally:
            self.after(0, lambda: self.start_btn.configure(state="normal"))
            self.progress.set(0)

    def open_folder(self, path):
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            self.log_msg(f"无法打开文件夹: {e}", "WARN")


if __name__ == "__main__":
    app = App()
    app.mainloop()