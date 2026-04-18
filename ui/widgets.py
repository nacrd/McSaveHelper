"""自定义 UI 组件"""
import customtkinter as ctk
from typing import Any

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