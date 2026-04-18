"""顶部导航栏混入类"""
import customtkinter as ctk

from ui.constants import COLORS
from ui.widgets import ModernButton, ModernProgressBar


class TopBarMixin:
    """提供顶部导航栏构建方法"""
    
    def _build_top_bar(self):
        """构建现代化顶部导航栏"""
        top_frame = ctk.CTkFrame(
            self.main_bg,
            fg_color=COLORS["bg_secondary"],
            corner_radius=0,
            height=75
        )
        top_frame.pack(fill="x")
        
        title_frame = ctk.CTkFrame(top_frame, fg_color="transparent")
        title_frame.pack(side="left", padx=25, pady=15)
        
        ctk.CTkLabel(
            title_frame,
            text="🌍",
            font=ctk.CTkFont(size=28),
            text_color=COLORS["accent_light"],
        ).pack(side="left", padx=(0, 10))
        
        title_label = ctk.CTkLabel(
            title_frame,
            text="MC Migrator Pro",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=COLORS["text_primary"],
        )
        title_label.pack(side="left")
        
        subtitle_label = ctk.CTkLabel(
            title_frame,
            text="存档迁移工具",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        subtitle_label.pack(side="left", padx=(8, 0))
        
        progress_container = ctk.CTkFrame(top_frame, fg_color="transparent")
        progress_container.pack(side="right", padx=25, pady=18)
        
        self.progress_label = ctk.CTkLabel(
            progress_container,
            text="就绪",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["accent_light"],
        )
        self.progress_label.pack(side="left", padx=(0, 12))
        
        self.progress = ModernProgressBar(
            progress_container,
            width=220,
            height=10,
        )
        self.progress.pack(side="left")
        self.progress.set(0)
        
        self.start_btn = ModernButton(
            top_frame,
            text="🚀 开始转换",
            width=140,
            height=40,
            command=self.start,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
        )
        self.start_btn.pack(side="right", padx=(0, 25), pady=18)