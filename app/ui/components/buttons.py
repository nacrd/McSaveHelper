"""应用命令按钮组件。"""
import asyncio
from typing import Optional, Callable, Any, cast

import flet as ft

from app.ui.utils import safe_update

from app.ui.theme import THEME


class McButton(ft.Container):
    """支持禁用态与悬停/按下反馈的命令按钮。"""

    def __init__(
        self,
        text: str,
        bgcolor: str,
        on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
        width: Optional[int] = None,
        height: int = 44,
        icon: Optional[ft.IconData] = None,
        text_color: Optional[str] = None,
    ) -> None:
        """创建按钮并构建内容与边框样式。

        Args:
            text: 按钮文案。
            bgcolor: 基础背景色（十六进制）。
            on_click: 点击回调。
            width: 可选固定宽度。
            height: 高度，默认 44。
            icon: 可选前置图标。
            text_color: 可选文字颜色。
        """
        self._text = text
        self._bgcolor = bgcolor
        self._bgcolor_hover = self._adjust_brightness(bgcolor, 1.15)
        self._bgcolor_pressed = self._adjust_brightness(bgcolor, 0.85)
        self._on_click_handler = on_click
        self._width = width
        self._height = height
        self._icon = icon
        self._text_color = text_color or THEME.text_primary
        self._disabled = False
        self._is_pressed = False
        self._is_focused = False
        self._button = ft.Button(
            content=self._build_content(),
            width=width,
            height=height,
            elevation=0,
            style=ft.ButtonStyle(
                padding=0,
                bgcolor=ft.Colors.TRANSPARENT,
                overlay_color=ft.Colors.TRANSPARENT,
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=self._handle_click,
            on_hover=self._handle_hover,
            on_focus=self._handle_focus,
            on_blur=self._handle_blur,
        )

        super().__init__(
            content=self._button,
            width=width,
            height=height,
            bgcolor=bgcolor,
            border=ft.Border.all(1, THEME.border_standard),
            border_radius=6,
            alignment=ft.alignment.Alignment(0, 0),
            tooltip=None,
            animate=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
        )

    def _adjust_brightness(self, color: str, factor: float) -> str:
        """Adjust color brightness by factor

        Args:
            color: Hex color string (e.g., "#55FF55")
            factor: Brightness adjustment factor (>1 lighter, <1 darker)

        Returns:
            str: Adjusted hex color
        """
        try:
            # Remove # prefix
            hex_color = color.lstrip("#")
            # Parse RGB values
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            # Adjust brightness
            r = min(255, max(0, int(r * factor)))
            g = min(255, max(0, int(g * factor)))
            b = min(255, max(0, int(b * factor)))
            return f"#{r:02X}{g:02X}{b:02X}"
        except (ValueError, TypeError, IndexError):
            return color

    def _handle_hover(self, e: ft.Event[ft.Button]) -> None:
        """Handle hover event with visual feedback"""
        if self._disabled:
            return

        try:
            if e.data == "true":
                # Hover state - brighter color and enhanced shadow
                self.bgcolor = self._bgcolor_hover
                self.shadow = ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=8,
                    color=THEME.shadow,
                    offset=ft.Offset(0, 2),
                )
            else:
                # Normal state
                self.bgcolor = self._bgcolor
                if not self._is_pressed:
                    self.shadow = None
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def _handle_click(self, e: Any = None) -> None:
        """Handle click event with pressed animation"""
        if self._disabled:
            return

        try:
            self._is_pressed = True
            self.bgcolor = self._bgcolor_pressed
            self.shadow = None  # Remove shadow when pressed
            self.border = ft.Border.all(1, THEME.border_dark)
            safe_update(self)

            # Execute click handler even if the visual update failed because the
            # button is not mounted yet (common in unit tests and rebuilds).
            if self._on_click_handler:
                self._on_click_handler(e)

            # Reset to normal state after brief delay. Prefer Flet's page task
            # scheduler because this handler can run without a raw asyncio
            # loop.
            self._schedule_reset_pressed_state()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass

    def _handle_focus(self, event: ft.Event[ft.Button]) -> None:
        """Show a visible focus ring for keyboard navigation."""
        del event
        if self._disabled:
            return
        self._is_focused = True
        self.border = ft.Border.all(THEME.focus_ring_width, THEME.focus_ring)
        safe_update(self)

    def _handle_blur(self, event: ft.Event[ft.Button]) -> None:
        """Restore the normal border when keyboard focus leaves."""
        del event
        self._is_focused = False
        if not self._is_pressed:
            self.border = ft.Border.all(1, THEME.border_standard)
        safe_update(self)

    def _schedule_reset_pressed_state(self) -> None:
        try:
            page = self.page
            if page is not None and hasattr(page, "run_task"):
                cast(ft.Page, page).run_task(self._reset_pressed_state)
                return
            asyncio.get_running_loop().create_task(self._reset_pressed_state())
        except RuntimeError:
            self._reset_pressed_state_sync()
        except Exception:
            # Page/task scheduler may be unavailable during teardown.
            pass

    async def _reset_pressed_state(self) -> None:
        """Reset button to normal state after pressed animation"""
        try:
            await asyncio.sleep(0.15)
            self._apply_normal_visual_state()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def _reset_pressed_state_sync(self) -> None:
        try:
            self._apply_normal_visual_state()
        except Exception:
            # UI best-effort: control may already be unmounted.
            pass
        safe_update(self)

    def _apply_normal_visual_state(self) -> None:
        """Restore default colors/borders after press animation."""
        self._is_pressed = False
        self.bgcolor = self._bgcolor
        self.border = ft.Border.all(
            THEME.focus_ring_width if self._is_focused else 1,
            THEME.focus_ring if self._is_focused else THEME.border_standard,
        )
        self.shadow = None

    def _build_content(self) -> ft.Row:
        icon_color = THEME.text_muted if self._disabled else self._text_color
        text_color = THEME.text_muted if self._disabled else self._text_color

        controls: list[ft.Control] = []
        if self._icon:
            controls.append(ft.Icon(self._icon, size=16, color=icon_color))
        else:
            controls.append(ft.Container(width=0))
        controls.append(ft.Text(
            self._text,
            size=13,
            weight=ft.FontWeight.BOLD,
            color=text_color,
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        ))

        return ft.Row(
            controls,
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    @property
    def disabled(self) -> bool:
        """是否禁用（禁用时半透明且忽略点击）。"""
        return self._disabled

    @disabled.setter
    def disabled(self, value: bool) -> None:
        """设置禁用态并重建内容颜色。

        Args:
            value: True 表示禁用。
        """
        self._disabled = value
        self.opacity = 0.5 if value else 1.0
        self._button.disabled = value
        self._button.content = self._build_content()

    def set_text(self, text: str) -> None:
        """更新按钮文案并重建内容。

        Args:
            text: 新文案。
        """
        self._text = text
        self._button.content = self._build_content()

    def set_on_click(
            self, on_click: Optional[Callable[[ft.ControlEvent], Any]]) -> None:
        """替换点击处理器。

        Args:
            on_click: 新回调；None 表示清除。
        """
        self._on_click_handler = on_click


def _mc_button(
    text: str,
    bgcolor: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 44,
    icon: Optional[ft.IconData] = None,
    text_color: Optional[str] = None,
) -> McButton:
    """创建带斜切边框的 Minecraft 风格按钮。

    Args:
        text: 按钮文案。
        bgcolor: 背景色。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 44。
        icon: 可选图标。
        text_color: 可选文字色。

    Returns:
        配置好的 ``McButton``。
    """
    return McButton(text, bgcolor, on_click, width, height, icon, text_color)


def btn_primary(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 44,
    icon: Optional[ft.IconData] = None,
) -> McButton:
    """主按钮（草地绿）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 44。
        icon: 可选图标。

    Returns:
        主色 ``McButton``。
    """
    return _mc_button(
        text,
        THEME.accent,
        on_click,
        width,
        height,
        icon,
        THEME.text_invert,
    )


def btn_ghost(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 44,
    icon: Optional[ft.IconData] = None,
) -> McButton:
    """次要按钮（石头灰）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 44。
        icon: 可选前置图标。

    Returns:
        次要色 ``McButton``。
    """
    return _mc_button(
        text,
        THEME.bg_elevated,
        on_click,
        width,
        height,
        icon,
        text_color=THEME.text_primary,
    )


def btn_success(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 44,
    icon: Optional[ft.IconData] = None,
) -> McButton:
    """成功按钮（绿宝石色）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 44。
        icon: 可选前置图标。

    Returns:
        成功色 ``McButton``。
    """
    return _mc_button(
        text,
        THEME.success,
        on_click,
        width,
        height,
        icon,
        text_color=THEME.text_invert,
    )


def btn_danger(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 44,
    icon: Optional[ft.IconData] = None,
) -> McButton:
    """危险按钮（红石红）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 44。
        icon: 可选前置图标。

    Returns:
        危险色 ``McButton``。
    """
    return _mc_button(
        text,
        THEME.mc_redstone,
        on_click,
        width,
        height,
        icon,
    )
