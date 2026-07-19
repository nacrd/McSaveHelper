"""Tests for ProgressManager's page and translation boundary."""
import asyncio
from typing import cast

import flet as ft

from app.core.progress_manager import ProgressManager


class FakePage:
    def __init__(self) -> None:
        self.updates = 0

    def run_task(self, handler, *args):
        return asyncio.run(handler(*args))

    def update(self) -> None:
        self.updates += 1


class QueuedPage(FakePage):
    def __init__(self) -> None:
        super().__init__()
        self.tasks = []

    def run_task(self, handler, *args):
        self.tasks.append((handler, args))

    def flush_reverse(self) -> None:
        for handler, args in reversed(self.tasks):
            asyncio.run(handler(*args))
        self.tasks.clear()


def test_progress_manager_updates_attached_controls() -> None:
    page = FakePage()
    manager = ProgressManager(
        cast(ft.Page, page),
        lambda key, default, **kwargs: (
            default.format(**kwargs) if kwargs else f"T:{default}"
        ),
    )
    container = manager.create_progress_ui()
    label = manager._progress_label
    assert label is not None

    assert container.visible is False
    assert label.value == "T:就绪"

    manager.show_progress("扫描中")
    assert container.visible is True
    assert label.value == "扫描中"

    manager.update_progress(0.42)
    assert label.value == "进度 42%"
    manager.update_progress(0.421)

    manager.hide_progress()
    assert container.visible is False
    assert label.value == "T:就绪"
    assert page.updates == 3


def test_progress_manager_coalesces_same_percent_updates() -> None:
    page = FakePage()
    manager = ProgressManager(
        cast(ft.Page, page),
        lambda key, default, **kwargs: default.format(**kwargs),
    )
    manager.create_progress_ui()

    manager.show_progress("扫描")
    manager.update_progress_with_task("扫描", 0.421)
    manager.update_progress_with_task("扫描", 0.429)

    assert page.updates == 2


def test_progress_callbacks_apply_latest_complete_state_out_of_order() -> None:
    page = QueuedPage()
    manager = ProgressManager(
        cast(ft.Page, page),
        lambda key, default, **kwargs: default.format(**kwargs),
    )
    container = manager.create_progress_ui()

    manager.set_progress_label("处理完成")
    manager.set_progress_value(1.0)
    page.flush_reverse()

    assert container.visible is True
    assert manager._progress_label is not None
    assert manager._progress_label.value == "处理完成"
    assert manager._progress_bar is not None
    assert manager._progress_bar.value == 1.0
