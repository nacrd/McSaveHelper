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

    manager.hide_progress()
    assert container.visible is False
    assert label.value == "T:就绪"
    assert page.updates == 3
