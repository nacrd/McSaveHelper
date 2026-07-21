import flet as ft

from app.ui.application_shell import (
    _build_bottom_bar,
    _build_content_shell,
    build_tab_definitions,
)
from app.ui.theme import THEME


def test_build_tab_definitions_keeps_stable_view_order() -> None:
    calls = []

    def translate(key: str, default: str) -> str:
        calls.append((key, default))
        return f"translated:{default}"

    tabs = build_tab_definitions(translate)

    assert [tab["id"] for tab in tabs] == [
        "explorer",
        "migrator",
        "save_repair",
        "backup_center",
        "compare",
        "mappings",
        "server_properties",
        "settings",
    ]
    assert tabs[0]["label"] == "translated:存档浏览器"
    assert calls[-1] == ("sidebar.settings", "设置")


def test_application_shell_uses_unframed_workspace_layout() -> None:
    main_row = ft.Row()
    progress_control = ft.Container(visible=False)

    shell = _build_content_shell(main_row)
    bottom_bar = _build_bottom_bar(progress_control)

    assert shell.content is main_row
    assert shell.padding is None
    assert shell.border is None
    assert shell.border_radius is None
    assert bottom_bar is progress_control
    assert bottom_bar.visible is False
    assert bottom_bar.bgcolor == THEME.bg_secondary
    assert bottom_bar.border is not None
    assert bottom_bar.border.top.color == THEME.border_subtle
