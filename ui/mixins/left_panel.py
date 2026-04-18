"""左侧面板混入类"""
import customtkinter as ctk

from ui.constants import COLORS
from ui.widgets import TerminalLikeTextbox, ModernEntry, ModernButton


class LeftPanelMixin:
    """提供左侧面板构建方法"""
    
    def _build_left_panel(self, parent):
        """构建现代化左侧面板"""
        # 目录设置
        dir_card = self._create_card(parent)
        dir_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(dir_card, "📁 存档目录配置", icon_only=False)
        
        self._add_labeled_entry(
            dir_card,
            "客户端存档",
            self.src_path,
            "选择世界文件夹 (包含 level.dat)",
            self.choose_src
        )
        self._add_labeled_entry(
            dir_card,
            "服务端根目录",
            self.dest_path,
            "默认为程序当前目录",
            self.choose_dest
        )
        
        name_frame = ctk.CTkFrame(dir_card, fg_color="transparent")
        name_frame.pack(fill="x", padx=20, pady=(8, 18))
        ctk.CTkLabel(
            name_frame,
            text="世界文件夹名",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(0, 6))
        ModernEntry(
            name_frame,
            textvariable=self.world_name,
            placeholder_text="例如: world",
            height=38,
        ).pack(fill="x")
        
        # 批量处理目录选择
        self.batch_frame = ctk.CTkFrame(dir_card, fg_color="transparent")
        self.batch_frame.pack(fill="x", padx=20, pady=(8, 0))
        ctk.CTkLabel(
            self.batch_frame,
            text="批量存档目录",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(0, 6))
        batch_entry_frame = ctk.CTkFrame(self.batch_frame, fg_color="transparent")
        batch_entry_frame.pack(fill="x")
        ModernEntry(
            batch_entry_frame,
            textvariable=self.batch_dir_path,
            placeholder_text="选择包含多个世界存档的目录",
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ModernButton(
            batch_entry_frame,
            text="📂 浏览",
            width=90,
            height=38,
            command=self.choose_batch_dir,
            fg_color=COLORS["bg_secondary"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_primary"]
        ).pack(side="right")
        ModernButton(
            batch_entry_frame,
            text="🔍 扫描",
            width=90,
            height=38,
            command=self.scan_batch_worlds,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"]
        ).pack(side="right", padx=(0, 10))
        
        # 批量扫描结果
        self.batch_result_label = ctk.CTkLabel(
            self.batch_frame,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        )
        self.batch_result_label.pack(anchor="w", pady=(6, 0))
        
        # 隐藏批量处理相关控件，直到启用批量模式
        self._toggle_batch_mode()
        
        # 手动玩家名
        manual_card = self._create_card(parent)
        manual_card.pack(fill="x", pady=(0, 18))
        self._add_section_title(manual_card, "👥 手动指定玩家 (选填)", icon_only=False)
        ModernEntry(
            manual_card,
            textvariable=self.manual_names,
            placeholder_text="多个玩家用英文逗号分隔，例如: Steve, Alex",
            height=38,
        ).pack(fill="x", padx=20, pady=(8, 18))
        
        # 日志区域
        log_header = ctk.CTkFrame(parent, fg_color="transparent")
        log_header.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            log_header,
            text="📋 运行日志",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        ModernButton(
            log_header,
            text="🗑️ 清空",
            width=80,
            height=32,
            command=self.clear_log,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_secondary"]
        ).pack(side="right")
        
        self.log = TerminalLikeTextbox(parent, height=220)
        self.log.pack(fill="both", expand=True)