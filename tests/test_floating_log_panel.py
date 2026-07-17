"""悬浮日志面板的 Flet 0.85 存储适配测试。"""
import asyncio
from typing import Any, cast

import flet as ft

from app.ui.components.floating_log_panel import (
    FloatingLogButton,
    FloatingLogPanel,
)


class FakePreferences:
    def __init__(self, values=None) -> None:
        self.values = dict(values or {})

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value) -> bool:
        self.values[key] = value
        return True


class FakePage:
    def __init__(self, values=None) -> None:
        self.width = 1000
        self.height = 700
        self.shared_preferences = FakePreferences(values)
        self.updates = 0

    def run_task(self, handler, *args, **kwargs) -> Any:
        return asyncio.run(handler(*args, **kwargs))

    def update(self) -> None:
        self.updates += 1


def test_floating_panel_loads_and_saves_shared_preferences() -> None:
    page = FakePage({
        FloatingLogPanel.STORAGE_KEY: ["120", "80"],
    })
    panel = FloatingLogPanel(cast(ft.Page, page))

    assert panel.left == 120
    assert panel.top == 80

    panel._offset_left = 200
    panel._offset_top = 140
    panel._save_position()

    assert page.shared_preferences.values[panel.STORAGE_KEY] == ["200", "140"]


def test_floating_button_uses_independent_position_key() -> None:
    page = FakePage({"floating_log_button_position": ["30", "40"]})
    panel = FloatingLogPanel(cast(ft.Page, page))
    button = FloatingLogButton(panel, cast(ft.Page, page))

    assert button.right == 30
    assert button.bottom == 40
