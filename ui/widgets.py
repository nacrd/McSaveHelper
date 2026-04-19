"""自定义 UI 组件"""
import customtkinter as ctk
from typing import Any, List, Dict, Tuple, Set, Optional
from pathlib import Path
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

    def add_line(self, message: str, level: str = "info") -> None:
        """
        添加一行日志，并自动应用颜色标签
        """
        # 根据级别选择标签
        tag = level.lower()
        if tag not in ["info", "success", "warn", "error", "api", "timestamp", "header", "separator"]:
            tag = "info"
        # 插入带标签的文本
        self.configure(state="normal")
        self.insert("end", message + "\n", tag)
        self.see("end")
        self.configure(state="disabled")


class ModernCard(ctk.CTkFrame):
    """现代化卡片组件，带有渐变背景和阴影效果"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=8,
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
            corner_radius=6,
            font=ctk.CTkFont(size=13, weight="bold"),
            **kwargs,
        )


class ModernEntry(ctk.CTkEntry):
    """现代化输入框组件，带有更好的焦点效果"""
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(
            master,
            corner_radius=6,
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


class MCAHeatmap(ctk.CTkFrame):
    """区块热力图组件，显示区域文件密度网格"""
    
    def __init__(self, master: Any, cell_size: int = 20, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.cell_size = cell_size
        self.cells: Dict[Tuple[int, int], ctk.CTkButton] = {}
        self.selected: Set[Tuple[int, int]] = set()
        self._build_grid()
    
    def _build_grid(self) -> None:
        """创建空网格（初始无数据）"""
        # 留待 set_region_files 填充
        pass
    
    def set_region_files(self, region_files: Dict[Tuple[int, int], Path]) -> None:
        """
        根据区域文件路径字典更新热力图。
        
        Args:
            region_files: 键为 (x, z) 坐标，值为区域文件路径
        """
        # 清除现有网格
        for cell in self.cells.values():
            cell.destroy()
        self.cells.clear()
        
        if not region_files:
            return
        
        # 计算坐标范围
        xs = [coord[0] for coord in region_files.keys()]
        zs = [coord[1] for coord in region_files.keys()]
        min_x, max_x = min(xs), max(xs)
        min_z, max_z = min(zs), max(zs)
        
        # 计算网格尺寸
        width = max_x - min_x + 1
        height = max_z - min_z + 1
        
        # 创建网格
        for z in range(height):
            for x in range(width):
                coord = (min_x + x, min_z + z)
                path = region_files.get(coord)
                # 创建单元格按钮
                btn = ctk.CTkButton(
                    self,
                    text="",
                    width=self.cell_size,
                    height=self.cell_size,
                    corner_radius=2,
                    fg_color=self._color_for_file(path),
                    border_width=1,
                    border_color=COLORS["border"],
                    hover_color=COLORS["bg_card_hover"],
                    command=lambda c=coord: self._on_cell_click(c)
                )
                btn.grid(row=z, column=x, padx=1, pady=1)
                self.cells[coord] = btn
        
        # 添加坐标标签（可选）
        # 调整网格权重
        for i in range(height):
            self.grid_rowconfigure(i, weight=0)
        for j in range(width):
            self.grid_columnconfigure(j, weight=0)
    
    def _color_for_file(self, path: Optional[Path]) -> str:
        """根据文件大小返回颜色（越深表示越大）"""
        if path is None or not path.exists():
            return COLORS["bg_card"]
        try:
            size = path.stat().st_size
            # 将大小映射到颜色强度（0-255）
            # 假设最大 10MB
            max_size = 10 * 1024 * 1024
            intensity = min(255, int(size / max_size * 255))
            # 从浅蓝到深蓝
            r = 100
            g = 150
            b = 200 + intensity // 3
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return COLORS["bg_card"]
    
    def _on_cell_click(self, coord: Tuple[int, int]) -> None:
        """单元格点击事件，切换选择状态"""
        if coord in self.selected:
            self.selected.remove(coord)
            self.cells[coord].configure(border_color=COLORS["border"])
        else:
            self.selected.add(coord)
            self.cells[coord].configure(border_color=COLORS["accent"])
    
    def get_selected(self) -> List[Tuple[int, int]]:
        """返回选中的坐标列表"""
        return list(self.selected)
    
    def clear_selection(self) -> None:
        """清空选择"""
        for coord in self.selected:
            if coord in self.cells:
                self.cells[coord].configure(border_color=COLORS["border"])
        self.selected.clear()



class NBTTreeView(ctk.CTkFrame):
    """NBT 树状视图组件，支持搜索和实时编辑"""
    
    def __init__(self, master: Any, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        # 暂时使用标签占位
        self.label = ctk.CTkLabel(
            self,
            text="NBT 树状视图（开发中）",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["text_secondary"]
        )
        self.label.pack(expand=True, padx=20, pady=20)
    
    def load_nbt(self, nbt_data: Any) -> None:
        """加载 NBT 数据到树中"""
        # 占位实现
        pass
    
    def search(self, query: str) -> None:
        """搜索 NBT 树中的键值"""
        pass
    
    def get_modified_data(self) -> Any:
        """返回修改后的 NBT 数据"""
        return None


class InventoryGrid(ctk.CTkFrame):
    """背包网格组件，显示 9x4 物品栏"""

    def __init__(self, master: Any, slot_size: int = 48, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.slot_size = slot_size
        self.slots: List[ctk.CTkButton] = []
        self._build_grid()

    def _build_grid(self) -> None:
        """创建空网格"""
        for row in range(4):
            for col in range(9):
                slot = ctk.CTkButton(
                    self,
                    text="",
                    width=self.slot_size,
                    height=self.slot_size,
                    corner_radius=6,
                    fg_color=COLORS["bg_card"],
                    border_width=1,
                    border_color=COLORS["border"],
                    hover_color=COLORS["bg_card_hover"],
                )
                slot.grid(row=row, column=col, padx=2, pady=2)
                self.slots.append(slot)

    def set_inventory(self, inventory: List[Dict[str, Any]]) -> None:
        """
        根据 inventory 列表更新网格显示。

        Args:
            inventory: 每个物品字典应包含:
                - slot (int): 0-35（背包+快捷栏）
                - id (str): 物品ID，例如 "minecraft:diamond"
                - count (int): 数量
                - tag (Optional[Compound]): 附加 NBT 标签
        """
        # 先清空所有格子
        for slot in self.slots:
            slot.configure(text="", image=None)

        # 映射 slot 索引到网格位置（Minecraft 背包布局）
        # 0-8 快捷栏（第4行），9-35 背包（第1-3行）
        for item in inventory:
            slot_idx = item.get("slot", -1)
            if not 0 <= slot_idx < 36:
                continue
            # 计算行列
            if slot_idx < 9:
                # 快捷栏 (第4行)
                row = 3
                col = slot_idx
            else:
                # 背包 (第1-3行)
                adjusted = slot_idx - 9
                row = adjusted // 9
                col = adjusted % 9
            # 获取对应的按钮
            btn = self.slots[row * 9 + col]
            # 设置显示文本（数量）
            count = item.get("count", 1)
            id_str = item.get("id", "")
            # 提取物品名称（去掉命名空间）
            display_name = id_str.split(":")[-1] if ":" in id_str else id_str
            btn.configure(text=f"{display_name}\n×{count}" if count > 1 else display_name)
            # TODO: 未来可以添加图标

    def clear(self) -> None:
        """清空网格"""
        for slot in self.slots:
            slot.configure(text="", image=None)


class PathSelectorWidget(ctk.CTkFrame):
    """路径选择器组件，包含标签、输入框和浏览按钮"""
    
    def __init__(self, master, label_text, var, placeholder, browse_cmd, scan_cmd=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.var = var
        self.browse_cmd = browse_cmd
        self.scan_cmd = scan_cmd
        
        # 标签
        self.label = ctk.CTkLabel(
            self,
            text=label_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        )
        self.label.pack(anchor="w", pady=(0, 6))
        
        # 输入框和按钮容器
        entry_frame = ctk.CTkFrame(self, fg_color="transparent")
        entry_frame.pack(fill="x")
        
        self.entry = ModernEntry(
            entry_frame,
            textvariable=var,
            placeholder_text=placeholder,
            height=38,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.browse_btn = ModernButton(
            entry_frame,
            text="📂 浏览",
            width=90,
            height=38,
            command=browse_cmd,
            fg_color=COLORS["bg_secondary"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_primary"]
        )
        self.browse_btn.pack(side="right")
        
        if scan_cmd:
            self.scan_btn = ModernButton(
                entry_frame,
                text="🔍 扫描",
                width=90,
                height=38,
                command=scan_cmd,
                fg_color=COLORS["accent"],
                hover_color=COLORS["accent_hover"]
            )
            self.scan_btn.pack(side="right", padx=(0, 10))
    
    def get_path(self):
        return self.var.get()
    
    def set_path(self, path):
        self.var.set(path)


class LogPanelWidget(ctk.CTkFrame):
    """日志面板组件，包含标题、清空按钮和可滚动的文本框"""
    
    def __init__(self, master, title="日志", height=200, clear_cmd=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        
        # 标题栏
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(0, 8))
        
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        
        if clear_cmd:
            ModernButton(
                header,
                text="🗑️ 清空",
                width=80,
                height=32,
                command=clear_cmd,
                fg_color=COLORS["bg_card"],
                hover_color=COLORS["border_light"],
                text_color=COLORS["text_secondary"]
            ).pack(side="right")
        
        self.textbox = TerminalLikeTextbox(self, height=height)
        self.textbox.pack(fill="both", expand=True)
    
    def log(self, message, level="info"):
        """添加日志消息"""
        self.textbox.add_line(message, level)
    
    def clear(self):
        """清空日志"""
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")


class ModeSelectorWidget(ctk.CTkFrame):
    """模式选择器组件（快速/完整模式）"""
    
    def __init__(self, master, var, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.var = var
        
        ctk.CTkRadioButton(
            self,
            text="⚡ 快速模式",
            variable=self.var,
            value="fast",
            font=ctk.CTkFont(size=14, weight="bold"),
            hover_color=COLORS["accent_light"]
        ).pack(side="left", padx=(0, 30))
        
        ctk.CTkRadioButton(
            self,
            text="🧠 完整模式",
            variable=self.var,
            value="full",
            font=ctk.CTkFont(size=14, weight="bold"),
            hover_color=COLORS["accent_light"]
        ).pack(side="left")
    
    def get_mode(self):
        return self.var.get()
    
    def set_mode(self, mode):
        self.var.set(mode)


class OptionGroupWidget(ctk.CTkFrame):
    """选项组组件，用于显示一组复选框"""
    
    def __init__(self, master, options, **kwargs):
        """
        options: 列表，每个元素为 (变量, 文本)
        """
        super().__init__(master, fg_color="transparent", **kwargs)
        self.options = []
        
        for var, text in options:
            chk = ModernCheckbox(self, text=text, variable=var)
            chk.pack(anchor="w", pady=6)
            self.options.append((var, chk))
    
    def get_values(self):
        return {text: var.get() for var, text in self.options}