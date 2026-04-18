"""自定义 UI 组件"""
import customtkinter as ctk

from .constants import COLORS


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