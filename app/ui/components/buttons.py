"""Minecraft 风格按钮组件。"""
import asyncio
from typing import Optional, Callable, Any, cast

import flet as ft

from app.ui.utils import safe_update

from app.ui.theme import THEME


class McButton(ft.Container):
    """Minecraft 风格按钮：支持禁用态与悬停/按下动画。

    保留斜切边框与圆角，点击时短暂反转边框并压暗背景。
    """

    def __init__(
        self,
        text: str,
        bgcolor: str,
        on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
        width: Optional[int] = None,
        height: int = 42,
        icon: Optional[ft.IconData] = None,
        text_color: Optional[str] = None,
    ) -> None:
        """创建按钮并构建内容与边框样式。

        Args:
            text: 按钮文案。
            bgcolor: 基础背景色（十六进制）。
            on_click: 点击回调。
            width: 可选固定宽度。
            height: 高度，默认 42。
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

        super().__init__(
            content=self._build_content(),
            width=width,
            height=height,
            bgcolor=bgcolor,
            border=ft.Border(
                left=ft.BorderSide(2, THEME.border_light),
                top=ft.BorderSide(2, THEME.border_light),
                right=ft.BorderSide(2, THEME.border_dark),
                bottom=ft.BorderSide(2, THEME.border_dark),
            ),
            border_radius=6,
            alignment=ft.alignment.Alignment(0, 0),
            on_click=self._handle_click,  # type: ignore[arg-type]
            on_hover=self._handle_hover,  # type: ignore[arg-type]
            ink=True,
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
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

    def _handle_hover(self, e: ft.ControlEvent) -> None:
        """Handle hover event with visual feedback"""
        if self._disabled:
            return

        try:
            if e.data == "true":
                # Hover state - brighter color and enhanced shadow
                self.bgcolor = self._bgcolor_hover
                self.shadow = ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=4,
                    color=THEME.shadow,
                    offset=ft.Offset(2, 2),
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
            # Pressed state - darker color and inverted border
            self._is_pressed = True
            self.bgcolor = self._bgcolor_pressed
            self.shadow = None  # Remove shadow when pressed
            self.border = ft.Border(
                left=ft.BorderSide(2, THEME.border_dark),
                top=ft.BorderSide(2, THEME.border_dark),
                right=ft.BorderSide(2, THEME.border_light),
                bottom=ft.BorderSide(2, THEME.border_light),
            )
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
        self.border = ft.Border(
            left=ft.BorderSide(2, THEME.border_light),
            top=ft.BorderSide(2, THEME.border_light),
            right=ft.BorderSide(2, THEME.border_dark),
            bottom=ft.BorderSide(2, THEME.border_dark),
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
            font_family="monospace",
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
        self.content = self._build_content()

    def set_text(self, text: str) -> None:
        """更新按钮文案并重建内容。

        Args:
            text: 新文案。
        """
        self._text = text
        self.content = self._build_content()

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
    height: int = 42,
    icon: Optional[ft.IconData] = None,
    text_color: Optional[str] = None,
) -> McButton:
    """创建带斜切边框的 Minecraft 风格按钮。

    Args:
        text: 按钮文案。
        bgcolor: 背景色。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 42。
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
    height: int = 42,
    icon: Optional[ft.IconData] = None,
) -> McButton:
    """主按钮（草地绿）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 42。
        icon: 可选图标。

    Returns:
        主色 ``McButton``。
    """
    return _mc_button(text, THEME.mc_grass, on_click, width, height, icon)


def btn_ghost(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 42,
) -> McButton:
    """次要按钮（石头灰）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 42。

    Returns:
        次要色 ``McButton``。
    """
    return _mc_button(text, THEME.mc_stone, on_click, width,
                      height, text_color=THEME.text_primary)


def btn_success(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 42,
) -> McButton:
    """成功按钮（绿宝石色）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 42。

    Returns:
        成功色 ``McButton``。
    """
    return _mc_button(text, THEME.mc_emerald, on_click, width, height)


def btn_danger(
    text: str,
    on_click: Optional[Callable[[ft.ControlEvent], Any]] = None,
    width: Optional[int] = None,
    height: int = 42,
) -> McButton:
    """危险按钮（红石红）。

    Args:
        text: 按钮文案。
        on_click: 点击回调。
        width: 可选宽度。
        height: 高度，默认 42。

    Returns:
        危险色 ``McButton``。
    """
    return _mc_button(text, THEME.mc_redstone, on_click, width, height)
