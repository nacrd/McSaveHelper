"""UI 通用工具混入类"""
import customtkinter as ctk
from typing import Any, Optional, Callable

from ui.constants import COLORS
from ui.widgets import ModernCard, ModernButton, ModernEntry, ModernCheckbox


class CommonUIMixin:
    """提供创建卡片、标题、带标签的输入框等通用 UI 方法"""
    
    def _create_card(self, parent: Any) -> ModernCard:
        """创建现代化卡片容器"""
        return ModernCard(parent)
    
    def _add_section_title(self, parent: Any, text: str, icon_only: bool = False) -> None:
        """添加现代化章节标题"""
        title_frame = ctk.CTkFrame(parent, fg_color="transparent")
        title_frame.pack(fill="x", padx=20, pady=(18, 8))
        
        ctk.CTkLabel(
            title_frame,
            text=text,
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text_primary"]
        ).pack(side="left")
        
        if not icon_only:
            separator = ctk.CTkFrame(title_frame, height=1, fg_color=COLORS["border"])
            separator.pack(side="left", fill="x", expand=True, padx=(15, 0))
    
    def _add_labeled_entry(self, parent: Any, label_text: str, var: Any,
                          placeholder: str, browse_cmd: Callable[[], None]) -> None:
        """添加带标签的现代化输入框和浏览按钮"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=8, padx=20)
        ctk.CTkLabel(
            frame,
            text=label_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_secondary"]
        ).pack(anchor="w", pady=(0, 6))
        entry_frame = ctk.CTkFrame(frame, fg_color="transparent")
        entry_frame.pack(fill="x")
        ModernEntry(
            entry_frame,
            textvariable=var,
            placeholder_text=placeholder,
            height=38,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ModernButton(
            entry_frame,
            text="📂 浏览",
            width=90,
            height=38,
            command=browse_cmd,
            fg_color=COLORS["bg_secondary"],
            hover_color=COLORS["border_light"],
            text_color=COLORS["text_primary"]
        ).pack(side="right")
    
    def _set_readonly_text(self, textbox: Any, content: str) -> None:
        """设置只读文本框的内容（线程安全）"""
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", content)
        textbox.configure(state="disabled")