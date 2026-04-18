"""顶部导航栏混入类"""
import customtkinter as ctk

from ui.constants import COLORS


class TopBarMixin:
    """提供顶部导航栏构建方法"""
    
    def _build_top_bar(self):
        """构建顶部导航栏"""
        top_frame = ctk.CTkFrame(
            self.main_bg,
            fg_color=COLORS["bg_secondary"],
            corner_radius=0,
            height=70
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
        self.progress_label.pack(side="left", padx=(0, 10))
        
        self.progress = ctk.CTkProgressBar(
            progress_container,
            width=200,
            height=8,
            progress_color=COLORS["accent"]
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
        self.start_btn.pack(side="right", padx=(0, 25), pady=15)