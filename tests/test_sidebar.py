"""侧边栏公开行为与 Flet 0.85 事件回归。"""
from typing import Iterator

import flet as ft

from app.ui.icons import IconSet
from app.ui.sidebar import Sidebar
from app.ui.theme import THEME


def _sidebar(**kwargs) -> Sidebar:
    return Sidebar(
        tabs=[
            {"id": "explorer", "label": "浏览", "icon": IconSet.EXPLORE},
            {"id": "settings", "label": "设置", "icon": IconSet.SETTINGS},
        ],
        on_tab_select=kwargs.pop("on_tab_select", lambda tab_id: None),
        default_tab="explorer",
        **kwargs,
    )


def test_sidebar_switches_tabs_and_collapsed_layout() -> None:
    selected = []
    sidebar = _sidebar(on_tab_select=selected.append)

    sidebar.select_tab("settings")
    sidebar.set_collapsed(True)

    assert sidebar.selected_id == "settings"
    assert selected == ["settings"]
    assert sidebar.is_collapsed is True
    assert sidebar.width == Sidebar.COLLAPSED_WIDTH


def test_sidebar_shell_commands_do_not_require_control_events() -> None:
    set_current = []
    sidebar = _sidebar(on_set_current_save=lambda: set_current.append(True))

    sidebar._handle_set_current_save()
    sidebar._toggle_recent()
    sidebar._handle_toggle()

    assert set_current == [True]
    assert sidebar._recent_expanded is True
    assert sidebar.is_collapsed is True


def _walk(control: ft.Control) -> Iterator[ft.Control]:
    yield control
    children = getattr(control, "controls", None)
    if children:
        for child in children:
            yield from _walk(child)
    content = getattr(control, "content", None)
    if isinstance(content, ft.Control):
        yield from _walk(content)


def test_sidebar_uses_shorter_expanded_width() -> None:
    sidebar = _sidebar()

    assert sidebar.width == 224
    sidebar.set_width(240)
    assert sidebar.width == 240


def test_recent_saves_are_usable_in_expanded_and_collapsed_modes() -> None:
    selected: list[str] = []
    path = r"C:\saves\demo"
    sidebar = _sidebar(
        on_recent_save_select=selected.append,
        recent_saves=[{"name": "演示世界", "path": path}],
    )
    sidebar.set_current_save_name("演示世界", path)

    item = sidebar._recent_save_col.controls[0]
    assert isinstance(item, ft.Container)
    assert item.bgcolor == THEME.bg_elevated
    assert sidebar._recent_save_col.height == 58

    sidebar.set_collapsed(True)
    header = sidebar._header_container.content
    assert isinstance(header, ft.Container)
    menus = [
        control
        for control in _walk(header)
        if isinstance(control, ft.PopupMenuButton)
    ]
    assert len(menus) == 1
    assert len(menus[0].items) == 1
    assert menus[0].tooltip == "最近存档"
    assert menus[0].bgcolor == THEME.bg_card
