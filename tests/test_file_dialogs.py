"""Tests for TkFileDialogs worker-thread lifecycle."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import flet as ft

from app.adapters.file_dialogs import TkFileDialogs
from app.core.window_manager import (
    WindowManager,
    WindowManagerDependencies,
)


class _FakeRoot:
    def __init__(self) -> None:
        self.destroyed = False
        self.withdrawn = False
        self.attributes_calls: list[tuple[Any, ...]] = []

    def withdraw(self) -> None:
        self.withdrawn = True

    def attributes(self, *args: Any) -> None:
        self.attributes_calls.append(args)

    def destroy(self) -> None:
        self.destroyed = True


def _patch_tk(root: _FakeRoot, fake_dialog: MagicMock):
    """Patch tkinter so the worker thread uses our fakes."""
    return (
        patch("tkinter.Tk", return_value=root),
        patch("tkinter.filedialog", fake_dialog, create=True),
    )


def test_close_is_idempotent_and_destroys_root() -> None:
    root = _FakeRoot()
    fake_dialog = MagicMock()
    tk_patch, fd_patch = _patch_tk(root, fake_dialog)

    with tk_patch, fd_patch:
        dialogs = TkFileDialogs()
        assert dialogs._ready.wait(timeout=2.0)
        dialogs.close()
        dialogs.close()  # second close must not raise

        assert root.destroyed is True
        assert not dialogs._thread.is_alive()


def test_pick_directory_returns_none_after_close() -> None:
    root = _FakeRoot()
    fake_dialog = MagicMock()
    tk_patch, fd_patch = _patch_tk(root, fake_dialog)

    with tk_patch, fd_patch:
        dialogs = TkFileDialogs()
        assert dialogs._ready.wait(timeout=2.0)
        dialogs.close()

        assert dialogs.pick_directory("x") is None


def test_pick_directory_delegates_to_tk_on_worker_thread() -> None:
    root = _FakeRoot()
    fake_dialog = MagicMock()
    worker_ids: list[int] = []

    def _record_askdirectory(**kwargs: Any) -> str:
        worker_ids.append(threading.get_ident())
        return "C:/worlds/demo"

    fake_dialog.askdirectory.side_effect = _record_askdirectory
    tk_patch, fd_patch = _patch_tk(root, fake_dialog)

    with tk_patch, fd_patch:
        dialogs = TkFileDialogs()
        try:
            assert dialogs._ready.wait(timeout=2.0)
            selected = dialogs.pick_directory("选择目录")
            assert selected == "C:/worlds/demo"
            assert worker_ids == [dialogs._thread.ident]
            fake_dialog.askdirectory.assert_called_once()
            call_kwargs = fake_dialog.askdirectory.call_args.kwargs
            assert call_kwargs["title"] == "选择目录"
            assert call_kwargs["parent"] is root
        finally:
            dialogs.close()


def test_pick_file_and_save_file_pass_filters() -> None:
    root = _FakeRoot()
    fake_dialog = MagicMock()
    fake_dialog.askopenfilename.return_value = "in.dat"
    fake_dialog.asksaveasfilename.return_value = "out.dat"
    tk_patch, fd_patch = _patch_tk(root, fake_dialog)

    with tk_patch, fd_patch:
        dialogs = TkFileDialogs()
        try:
            assert dialogs._ready.wait(timeout=2.0)
            assert dialogs.pick_file("open", [("DAT", "*.dat")]) == "in.dat"
            assert (
                dialogs.save_file("save", ".dat", [("DAT", "*.dat")])
                == "out.dat"
            )
            open_kwargs = fake_dialog.askopenfilename.call_args.kwargs
            save_kwargs = fake_dialog.asksaveasfilename.call_args.kwargs
            assert open_kwargs["filetypes"] == [("DAT", "*.dat")]
            assert save_kwargs["defaultextension"] == ".dat"
        finally:
            dialogs.close()


def test_window_manager_shutdown_disposes_file_dialogs() -> None:
    disposed: list[str] = []
    page = cast(
        ft.Page,
        SimpleNamespace(
            window=SimpleNamespace(
                prevent_close=True,
                destroy=MagicMock(),
                close=MagicMock(),
            ),
            run_task=lambda coro: disposed.append("run_task"),
        ),
    )

    manager = WindowManager(WindowManagerDependencies(
        page=page,
        translate=lambda key, default: default,
        apply_responsive_layout=lambda layout: None,
        get_sidebar_mode=lambda: "auto",
        stop_gui_optimizer=lambda: disposed.append("optimizer"),
        dispose_views=lambda: disposed.append("views"),
        dispose_file_dialogs=lambda: disposed.append("file_dialogs"),
    ))

    with patch("app.ui.utils.set_app_closing"), patch(
        "core.logger.logger.shutdown", create=True
    ):
        manager.shutdown()

    assert "optimizer" in disposed
    assert "views" in disposed
    assert "file_dialogs" in disposed
