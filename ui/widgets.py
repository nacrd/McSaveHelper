"""自定义 UI 组件"""
import customtkinter as ctk
from typing import Any
from tkinter import filedialog, messagebox

from .constants import COLORS


class TerminalLikeTextbox(ctk.CTkTextbox):
    """自定义终端风格文本框，自动添加前缀和颜色标记"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            font=ctk.CTkFont(family="Cascadia Code", size=11),
            fg_color=COLORS["log_bg"],
            border_width=1,
            border_color=COLORS["log_border"],
            corner_radius=8,
            **kwargs,
        )
        self._configure_tags()

    def _configure_tags(self) -> None:
        self.tag_config("info", foreground=COLORS["text_primary"])
        self.tag_config("success", foreground=COLORS["terminal_green"])
        self.tag_config("warn", foreground=COLORS["terminal_yellow"])
        self.tag_config("error", foreground=COLORS["terminal_red"])
        self.tag_config("api", foreground=COLORS["terminal_blue"])
        self.tag_config("timestamp", foreground=COLORS["text_muted"])
        self.tag_config("header", foreground=COLORS["accent_light"])
        self.tag_config("separator", foreground=COLORS["border_light"])


class ModernCard(ctk.CTkFrame):
    """现代化卡片组件，带有渐变背景和阴影效果"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=16,
            fg_color=COLORS["bg_card"],
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self._hover_bind()
    
    def _hover_bind(self) -> None:
        self.bind("<Enter>", lambda e: self.configure(border_color=COLORS["border_light"]))
        self.bind("<Leave>", lambda e: self.configure(border_color=COLORS["border"]))


class ModernButton(ctk.CTkButton):
    """现代化按钮组件，带有更好的视觉效果"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            **kwargs,
        )


class ModernEntry(ctk.CTkEntry):
    """现代化输入框组件，带有更好的焦点效果"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=8,
            border_width=1,
            border_color=COLORS["border"],
            **kwargs,
        )
        self._focus_bind()
    
    def _focus_bind(self) -> None:
        self.bind("<FocusIn>", lambda e: self.configure(border_color=COLORS["accent"]))
        self.bind("<FocusOut>", lambda e: self.configure(border_color=COLORS["border"]))


class ModernCheckbox(ctk.CTkCheckBox):
    """现代化复选框组件"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            **kwargs,
        )


class ModernProgressBar(ctk.CTkProgressBar):
    """现代化进度条组件"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=10,
            progress_color=COLORS["accent"],
            **kwargs,
        )


class UUIDMappingRow(ctk.CTkFrame):
    """UUID映射表格中的一行"""
    def __init__(self, master, player_name="", uuid="", on_change=None, on_delete=None):
        super().__init__(master, fg_color="transparent")
        self.on_change = on_change
        self.on_delete = on_delete
        
        # 拖拽手柄
        self.drag_handle = ctk.CTkLabel(self, text="☰", width=20, cursor="hand2")
        self.drag_handle.grid(row=0, column=0, padx=(0, 5), sticky="w")
        
        # 玩家名输入框
        self.player_var = ctk.StringVar(value=player_name)
        self.player_entry = ModernEntry(self, textvariable=self.player_var, width=120)
        self.player_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        self.player_var.trace_add("write", self._handle_change)
        
        # UUID输入框
        self.uuid_var = ctk.StringVar(value=uuid)
        self.uuid_entry = ModernEntry(self, textvariable=self.uuid_var, width=250)
        self.uuid_entry.grid(row=0, column=2, padx=5, pady=2, sticky="ew")
        self.uuid_var.trace_add("write", self._handle_change)
        
        # 删除按钮
        self.delete_btn = ModernButton(self, text="×", width=30, command=self._delete)
        self.delete_btn.grid(row=0, column=3, padx=(5, 0))
        
        # 配置列权重
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=2)
    
    def _handle_change(self, *args):
        if self.on_change:
            self.on_change(self.get_data())
    
    def _delete(self):
        if self.on_delete:
            self.on_delete(self)
    
    def get_data(self):
        return (self.player_var.get().strip(), self.uuid_var.get().strip())
    
    def set_data(self, player_name, uuid):
        self.player_var.set(player_name)
        self.uuid_var.set(uuid)


class UUIDMappingTable(ctk.CTkFrame):
    """可视化UUID映射编辑器表格"""
    def __init__(self, master, mappings=None, on_mappings_change=None):
        super().__init__(master, fg_color="transparent")
        self.mappings = mappings or {}
        self.on_mappings_change = on_mappings_change
        self.rows = []  # UUIDMappingRow 实例列表
        
        # 表头
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(self.header_frame, text="玩家名", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, padx=5)
        ctk.CTkLabel(self.header_frame, text="UUID", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=5)
        
        # 行容器（可滚动）
        self.rows_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, columnspan=4, sticky="nsew")
        
        # 按钮工具栏
        self.toolbar_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.toolbar_frame.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        
        ModernButton(self.toolbar_frame, text="+ 添加一行", command=self._add_row).pack(side="left", padx=(0, 10))
        ModernButton(self.toolbar_frame, text="📁 导入名单", command=self._import_mappings).pack(side="left", padx=(0, 10))
        ModernButton(self.toolbar_frame, text="💾 导出名单", command=self._export_mappings).pack(side="left", padx=(0, 10))
        ModernButton(self.toolbar_frame, text="🗑️ 清空", command=self._clear_all, fg_color=COLORS["error"]).pack(side="left")
        
        # 配置网格权重
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # 初始加载映射
        self._load_mappings()
    
    def _load_mappings(self):
        """从当前映射字典加载行"""
        # 清除现有行
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        
        # 创建新行
        row_index = 0
        for player_name, uuid in self.mappings.items():
            row = UUIDMappingRow(
                self.rows_frame,
                player_name=player_name,
                uuid=uuid,
                on_change=self._on_row_change,
                on_delete=self._on_row_delete
            )
            row.grid(row=row_index, column=0, columnspan=4, sticky="ew", pady=2)
            self.rows.append(row)
            row_index += 1
    
    def _add_row(self, player_name="", uuid=""):
        """添加新行"""
        row = UUIDMappingRow(
            self.rows_frame,
            player_name=player_name,
            uuid=uuid,
            on_change=self._on_row_change,
            on_delete=self._on_row_delete
        )
        row.grid(row=len(self.rows), column=0, columnspan=4, sticky="ew", pady=2)
        self.rows.append(row)
        self._update_mappings()
    
    def _on_row_change(self, data):
        """当行数据改变时更新映射"""
        self._update_mappings()
    
    def _on_row_delete(self, row):
        """删除行"""
        row.destroy()
        self.rows.remove(row)
        self._update_mappings()
        # 重新布局行索引
        for i, r in enumerate(self.rows):
            r.grid(row=i)
    
    def _update_mappings(self):
        """从所有行重建映射字典"""
        new_mappings = {}
        for row in self.rows:
            player_name, uuid = row.get_data()
            if player_name and uuid:
                new_mappings[player_name] = uuid
        self.mappings = new_mappings
        if self.on_mappings_change:
            self.on_mappings_change(new_mappings)
    
    def _import_mappings(self):
        """导入映射（从文本文件）"""
        import re
        file_path = filedialog.askopenfilename(
            title="选择映射文件",
            filetypes=[("文本文件", "*.txt"), ("CSV文件", "*.csv"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("导入错误", f"无法读取文件: {e}")
            return
        
        # 解析映射
        new_mappings = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 支持格式: 玩家名 UUID  或 玩家名,UUID  或 玩家名:UUID
            parts = re.split(r'[\s,:;]+', line, maxsplit=1)
            if len(parts) != 2:
                continue
            player_name, uuid = parts[0].strip(), parts[1].strip()
            # 验证UUID格式（可选）
            if player_name and uuid:
                new_mappings[player_name] = uuid
        
        if not new_mappings:
            messagebox.showwarning("导入结果", "未找到有效的映射")
            return
        
        # 询问用户是替换还是追加
        import tkinter as tk
        answer = messagebox.askyesnocancel("导入方式", "是否替换现有映射？\n\n点击'是'替换现有映射，点击'否'追加到现有映射。")
        if answer is None:
            return  # 取消
        if answer:  # 替换
            self.mappings = new_mappings
        else:  # 追加
            self.mappings.update(new_mappings)
        
        self._load_mappings()
        if self.on_mappings_change:
            self.on_mappings_change(self.mappings)
        
        messagebox.showinfo("导入成功", f"已导入 {len(new_mappings)} 个映射")
    
    def _export_mappings(self):
        """导出映射到文本文件"""
        if not self.mappings:
            messagebox.showwarning("导出警告", "没有可导出的映射")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="保存映射文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("CSV文件", "*.csv"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        
        lines = []
        for player_name, uuid in self.mappings.items():
            lines.append(f"{player_name} {uuid}")
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            messagebox.showinfo("导出成功", f"映射已导出到: {file_path}")
        except Exception as e:
            messagebox.showerror("导出错误", f"无法保存文件: {e}")
    
    def _clear_all(self):
        """清空所有映射"""
        for row in self.rows:
            row.destroy()
        self.rows.clear()
        self.mappings = {}
        if self.on_mappings_change:
            self.on_mappings_change({})
    
    def get_mappings(self):
        """返回当前映射字典"""
        return self.mappings.copy()
    
    def set_mappings(self, mappings):
        """设置映射字典并刷新表格"""
        self.mappings = mappings.copy()
        self._load_mappings()