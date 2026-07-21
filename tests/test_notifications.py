"""Flet 0.85 notification API regression tests."""
from typing import cast

import flet as ft

from app.ui.notifications import NotificationManager


class FakePage:
    def __init__(self) -> None:
        self.shown = []
        self.updates = 0

    def show_dialog(self, control: ft.Control) -> None:
        self.shown.append(control)

    def update(self) -> None:
        self.updates += 1


def test_notification_manager_uses_dialog_control_api() -> None:
    page = FakePage()
    manager = NotificationManager(cast(ft.Page, page))

    manager.show_success("完成")
    loading = manager.show_loading("处理中")

    assert isinstance(page.shown[0], ft.SnackBar)
    snackbar_content = page.shown[0].content
    assert isinstance(snackbar_content, ft.Row)
    assert isinstance(snackbar_content.controls[0], ft.Icon)
    assert isinstance(snackbar_content.controls[1], ft.Text)
    assert snackbar_content.controls[1].value == "完成"
    assert page.shown[1] is loading
    assert manager._current_dialog is loading

    manager.hide_loading(loading)

    assert loading.open is False
    assert manager._current_dialog is None


def test_notification_manager_closes_tracked_dialog() -> None:
    page = FakePage()
    manager = NotificationManager(cast(ft.Page, page))
    dialog = manager.show_custom_dialog("标题", ft.Text("内容"))

    manager.close_dialog()

    assert dialog.open is False
    assert manager._current_dialog is None
