"""按钮组件测试。"""
from typing import cast

import flet as ft

from app.ui.components.buttons import McButton, btn_ghost, btn_primary
from app.ui.theme import THEME


def test_primary_button_disabled_state_updates_content():
    btn = btn_primary("测试按钮")

    assert hasattr(btn, "disabled")
    assert btn.disabled is False

    btn.disabled = True
    assert btn.disabled is True
    assert btn.opacity == 0.5

    btn.disabled = False
    assert btn.disabled is False
    assert btn.opacity == 1.0


def test_button_text_and_click_handler_can_be_replaced():
    btn = btn_ghost("旧文本")
    called = []

    btn.set_text("新文本")
    btn.set_on_click(lambda e: called.append("clicked"))
    btn._handle_click(None)

    assert called == ["clicked"]
    assert btn.disabled is False


def test_button_reset_scheduling_is_safe_without_page_or_event_loop():
    btn = McButton("测试", "#55FF55")
    btn._is_pressed = True
    btn._schedule_reset_pressed_state()

    assert btn._is_pressed is False


def test_button_uses_focusable_surface_and_visible_focus_ring():
    btn = btn_primary("键盘操作")

    assert isinstance(btn.content, ft.Button)
    btn._handle_focus(cast(ft.Event[ft.Button], None))

    assert btn._is_focused is True
    assert btn.border is not None
    assert btn.border.left.color == THEME.focus_ring

    btn._handle_blur(cast(ft.Event[ft.Button], None))
    assert btn._is_focused is False
    assert btn.border.left.color == THEME.border_standard
