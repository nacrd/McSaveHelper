"""日志面板组件 —— 终端风格的滚动日志"""
import flet as ft

from app.ui.theme import THEME


class LogPanel(ft.Column):
    """可滚动的日志面板，最多保留 500 行"""

    def __init__(self) -> None:
        super().__init__(spacing=2, scroll=ft.ScrollMode.ALWAYS)
        self.expand = True
        self._max_lines = 500

    def log(self, message: str, level: str = "info") -> None:
        color_map = {
            "info": THEME.text_primary,
            "success": THEME.terminal_green,
            "warn": THEME.terminal_yellow,
            "error": THEME.terminal_red,
            "api": THEME.terminal_blue,
            "timestamp": THEME.text_muted,
            "header": THEME.accent_light,
            "separator": THEME.border_tertiary,
        }
        self.controls.append(
            ft.Text(
                message,
                color=color_map.get(level, THEME.text_primary),
                size=11,
                font_family="monospace",
            )
        )
        while len(self.controls) > self._max_lines:
            self.controls.pop(0)
        self.update()

    def clear(self) -> None:
        self.controls.clear()
        self.update()
