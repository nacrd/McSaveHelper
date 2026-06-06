"""独立日志面板组件 —— 底部可折叠面板，终端风格滚动日志"""
import flet as ft

from app.ui.theme import THEME


def _safe_update(control: ft.Control) -> None:
    """安全更新控件，若控件未挂载到页面则静默跳过"""
    try:
        control.update()
    except RuntimeError:
        pass


class LogPanel(ft.Container):
    """底部可折叠的独立日志面板

    包含：
      - 标题栏（带折叠/展开按钮和清除按钮）
      - 滚动日志区域（终端风格，最多 500 行）
    """

    DEFAULT_HEIGHT = 220
    COLLAPSED_HEIGHT = 36

    def __init__(self, title: str = "日志") -> None:
        self._expanded: bool = True
        self._max_lines: int = 500
        self._title: str = title

        # 日志内容区
        self._log_col = ft.Column(
            spacing=2,
            scroll=ft.ScrollMode.AUTO,
            auto_scroll=True,
        )
        self._log_col.expand = True

        # 标题栏按钮
        self._toggle_icon = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=16, color=THEME.text_secondary)
        self._toggle_btn = ft.Container(
            content=self._toggle_icon,
            on_click=self._toggle,
            padding=4,
            border_radius=4,
        )
        self._clear_btn = ft.Container(
            content=ft.Icon(ft.Icons.DELETE_OUTLINE, size=14, color=THEME.text_quaternary),
            on_click=lambda e: self.clear(),
            padding=4,
            border_radius=4,
            tooltip="清除日志",
        )
        self._title_text = ft.Text(
            f" ▣ {title}",
            size=12,
            color=THEME.mc_gold,
            weight=ft.FontWeight.BOLD,
            font_family="monospace",
        )
        self._count_text = ft.Text(
            "",
            size=10,
            color=THEME.text_quaternary,
        )

        # 标题栏
        header = ft.Container(
            content=ft.Row(
                [
                    self._toggle_btn,
                    self._title_text,
                    self._count_text,
                    ft.Container(expand=True),
                    self._clear_btn,
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            height=self.COLLAPSED_HEIGHT,
            padding=ft.Padding(left=8, right=8, top=4, bottom=4),
            bgcolor=THEME.mc_coal,
            border_radius=0,
            border=ft.Border(
                left=None,
                top=None,
                right=None,
                bottom=ft.BorderSide(2, THEME.border_tertiary),
            ),
        )

        # 日志容器
        self._log_container = ft.Container(
            content=self._log_col,
            padding=ft.Padding(left=12, right=12, top=4, bottom=8),
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None, top=ft.BorderSide(1, THEME.border_tertiary),
                right=None, bottom=None,
            ),
        )

        # 整体布局
        self._body = ft.Column(
            [header, self._log_container],
            spacing=0,
        )
        self._body.expand = True

        super().__init__(
            content=self._body,
            height=self.DEFAULT_HEIGHT,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None,
                top=ft.BorderSide(1, THEME.border_tertiary),
                right=None,
                bottom=None,
            ),
        )

    def _toggle(self, e: ft.ControlEvent = None) -> None:
        """折叠/展开日志面板"""
        try:
            self._expanded = not self._expanded
            if self._expanded:
                self.height = self.DEFAULT_HEIGHT
                self._toggle_icon.name = ft.Icons.KEYBOARD_ARROW_DOWN
                if len(self._body.controls) < 2:
                    self._body.controls.append(self._log_container)
            else:
                self.height = self.COLLAPSED_HEIGHT
                self._toggle_icon.name = ft.Icons.KEYBOARD_ARROW_RIGHT
                if len(self._body.controls) >= 2:
                    self._body.controls.pop()
            _safe_update(self)
        except Exception:
            pass

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
        self._log_col.controls.append(
            ft.Text(
                message,
                color=color_map.get(level, THEME.text_primary),
                size=11,
                font_family="monospace",
            )
        )
        while len(self._log_col.controls) > self._max_lines:
            self._log_col.controls.pop(0)
        # 更新计数
        self._count_text.value = f"({len(self._log_col.controls)})"
        _safe_update(self._log_col)
        _safe_update(self._count_text)

    def clear(self) -> None:
        self._log_col.controls.clear()
        self._count_text.value = ""
        _safe_update(self._log_col)
        _safe_update(self._count_text)
