"""Tests for DialogManager's explicit dependency boundary."""
from typing import cast

import flet as ft

from app.adapters.file_dialogs import FileTypes
from app.core.dialog_manager import DialogManager, DialogManagerDependencies


class FakePage:
    def __init__(self) -> None:
        self.overlay = []
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


class FakeFileDialogs:
    def __init__(self) -> None:
        self.calls = []

    def pick_directory(self, title: str):
        self.calls.append(("directory", title))
        return "world"

    def pick_file(self, title: str, file_types: FileTypes):
        self.calls.append(("open", title, list(file_types)))
        return "input.dat"

    def pick_files(self, title: str, file_types: FileTypes):
        self.calls.append(("open_many", title, list(file_types)))
        return ["input.dat"]

    def save_file(
        self,
        title: str,
        default_ext: str,
        file_types: FileTypes,
    ):
        self.calls.append(("save", title, default_ext, list(file_types)))
        return "output.dat"


def _manager():
    page = FakePage()
    switched = []
    removed = []
    copied = []
    snackbars = []
    file_dialogs = FakeFileDialogs()
    manager = DialogManager(DialogManagerDependencies(
        page=cast(ft.Page, page),
        translate=lambda key, default: f"T:{default}",
        switch_view=switched.append,
        remove_view=lambda view_id: removed.append(view_id),
        copy_to_clipboard=copied.append,
        show_snackbar=lambda message, color, duration: snackbars.append(
            (message, color, duration)
        ),
        file_dialogs=file_dialogs,
    ))
    return manager, page, switched, removed, copied, snackbars, file_dialogs


def test_dialog_manager_shows_and_closes_without_application() -> None:
    manager, page, _, _, _, _, _ = _manager()

    manager.info_dialog("标题", "消息")

    assert len(page.overlay) == 1
    assert page.overlay[0].open is True
    assert page.updates == 1

    manager.close_dialog()
    assert page.overlay[0].open is False
    assert page.updates == 2


def test_dialog_manager_uses_injected_navigation_commands() -> None:
    manager, _, switched, removed, _, _, _ = _manager()

    manager._close_error_view()
    manager._retry_view("broken")

    assert removed == ["error", "broken"]
    assert switched == ["explorer", "broken"]


def test_dialog_manager_clipboard_feedback_uses_page_adapter() -> None:
    manager, _, _, _, copied, snackbars, _ = _manager()

    manager._handle_copy("traceback")

    assert copied == ["traceback"]
    assert snackbars[0][0] == "错误信息已复制到剪贴板"


def test_error_placeholder_is_a_control() -> None:
    manager, _, _, _, _, _, _ = _manager()

    placeholder = manager.build_error_placeholder(
        "broken",
        RuntimeError("boom"),
    )

    assert isinstance(placeholder, ft.Container)


def test_file_selection_uses_injected_platform_adapter() -> None:
    manager, _, _, _, _, _, file_dialogs = _manager()

    assert manager.pick_directory() == "world"
    assert manager.pick_file() == "input.dat"
    assert manager.save_file(default_ext=".dat") == "output.dat"
    assert [call[0] for call in file_dialogs.calls] == [
        "directory",
        "open",
        "save",
    ]
