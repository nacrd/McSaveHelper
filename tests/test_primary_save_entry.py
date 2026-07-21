"""Primary save-selection entry points remain visible in compact layouts."""
from typing import cast

import flet as ft

from app.ui.sidebar_chrome import build_header_collapsed
from app.ui.views.explorer.world_info_panel import WorldInfoPanel


def test_collapsed_sidebar_keeps_save_picker_touch_target() -> None:
    calls: list[None] = []

    header = build_header_collapsed(lambda _event=None: calls.append(None))

    column = cast(ft.Column, header.content)
    save_button = cast(ft.Container, column.controls[1])
    assert save_button.width == 44
    assert save_button.height == 44
    assert save_button.tooltip == "设置当前存档"
    assert save_button.on_click is not None


def test_world_empty_state_exposes_direct_save_picker() -> None:
    calls: list[None] = []
    panel = WorldInfoPanel(on_select_save=lambda: calls.append(None))

    panel._handle_select_save(cast(ft.ControlEvent, None))

    assert calls == [None]
