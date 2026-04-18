"""设置视图（占位符）"""
import customtkinter as ctk
from typing import Any
from ui.constants import COLORS


class SettingsView(ctk.CTkFrame):
    """设置视图"""
    
    def __init__(self, master: Any, **kwargs) -> None:
        # 确保背景透明，移除可能冲突的fg_color参数
        kwargs.pop('fg_color', None)
        super().__init__(master, fg_color="transparent", **kwargs)
        self._build_ui()
    
    def _build_ui(self) -> None:
        ctk.CTkLabel(
            self,
            text="设置功能开发中",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(expand=True)