"""Qt 任务导航与世界上下文栏回归测试。"""
from __future__ import annotations

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QPushButton, QStackedWidget

from app.qtui.registry import create_qt_registry
from app.qtui.shell import QtShell
from app.qtui.sidebar import QtSidebar
from app.qtui.theme import DARK_THEME, get_theme_manager
from app.qtui.view_actions import QtViewAction
from app.qtui.world_context_bar import QtWorldContextBar


def _translate(_key: str, default: str = "", **_kwargs: object) -> str:
    return default


def test_registry_maps_world_navigation_to_shared_explorer(
    qt_app: object,
) -> None:
    del qt_app
    registry = create_qt_registry()
    world_navigation = registry.navigation[:6]

    assert [item.navigation_id for item in world_navigation] == [
        "world_overview",
        "world_players",
        "world_map",
        "world_stats",
        "world_search",
        "world_nbt",
    ]
    assert {item.view_id for item in world_navigation} == {"explorer"}
    assert [item.workspace_id for item in world_navigation] == [
        "world_info",
        "players",
        "map",
        "stats",
        "search",
        "nbt",
    ]


def test_sidebar_restores_navigation_width_after_auto_expand(
    qt_app: object,
) -> None:
    del qt_app
    sidebar = QtSidebar(
        tabs=[{
            "id": "world_overview",
            "group": "世界",
            "label": "概览",
            "icon": "O",
        }],
        translate=_translate,
        on_tab_select=lambda _view_id: None,
    )

    sidebar.set_collapsed(True)
    sidebar.set_collapsed(False)

    button = sidebar._buttons["world_overview"]
    assert button.maximumWidth() > 44
    assert button._text_label is not None
    assert button._text_label.text() == "概览"
    sidebar.deleteLater()


def test_sidebar_reuses_layout_during_repeated_collapse_and_selection(
    qt_app: QApplication,
) -> None:
    messages: list[str] = []
    previous_handler = qInstallMessageHandler(
        lambda _type, _context, message: messages.append(message)
    )
    sidebar = QtSidebar(
        tabs=[
            {"id": "overview", "label": "概览", "icon": "O"},
            {"id": "players", "label": "玩家", "icon": "P"},
        ],
        translate=_translate,
        on_tab_select=lambda _view_id: None,
    )

    try:
        sidebar.select_tab("overview")
        for _iteration in range(3):
            sidebar.set_collapsed(True)
            sidebar.select_tab("players")
            qt_app.processEvents()
            sidebar.set_collapsed(False)
            sidebar.select_tab("overview")
            qt_app.processEvents()
    finally:
        qInstallMessageHandler(previous_handler)

    overview = sidebar._buttons["overview"]
    assert overview._marker is not None
    assert overview._marker.text() == ""
    assert not any("already has a layout" in message for message in messages)
    sidebar.deleteLater()


def test_sidebar_refreshes_inline_colors_after_theme_switch(
    qt_app: QApplication,
) -> None:
    del qt_app
    sidebar = QtSidebar(
        tabs=[{"id": "overview", "label": "概览", "icon": "O"}],
        translate=_translate,
        on_tab_select=lambda _view_id: None,
    )
    manager = get_theme_manager()
    previous_mode = manager.mode
    try:
        sidebar.select_tab("overview")
        manager.set_mode("dark")
        sidebar.refresh_theme()

        assert DARK_THEME.bg_secondary in sidebar.styleSheet()
        assert DARK_THEME.accent_dim in sidebar._buttons["overview"].styleSheet()
    finally:
        manager.set_mode(previous_mode)
        sidebar.deleteLater()


def test_shell_projects_initial_action_enabled_state(qt_app: object) -> None:
    del qt_app
    sidebar = QtSidebar(
        tabs=[{"id": "overview", "label": "概览", "icon": "O"}],
        translate=_translate,
        on_tab_select=lambda _view_id: None,
    )
    shell = QtShell(
        translate=_translate,
        sidebar=sidebar,
        view_stack=QStackedWidget(),
        on_view_action=lambda _action: None,
        on_pick_world=lambda: None,
        on_recent_world=lambda _path: None,
        on_quick_backup=lambda: None,
    )

    shell.set_view_actions([
        QtViewAction("取消迁移", lambda: None, "danger", enabled=False)
    ])

    assert len(shell._action_buttons) == 1
    assert shell._action_buttons[0].isEnabled() is False
    shell.deleteLater()


def test_world_context_disables_backup_until_world_is_selected(
    qt_app: object,
) -> None:
    del qt_app
    recent_paths: list[str] = []
    bar = QtWorldContextBar(
        translate=_translate,
        on_pick_world=lambda: None,
        on_recent_world=recent_paths.append,
        on_quick_backup=lambda: None,
    )
    backup_button = next(
        button
        for button in bar.findChildren(QPushButton)
        if "快速备份" in button.text()
    )

    assert not backup_button.isEnabled()
    bar.set_current_save("C:/worlds/Demo", detail="Minecraft 1.21")
    assert backup_button.isEnabled()
    assert bar._world_name.text() == "Demo"
    assert bar._world_detail.text() == "Minecraft 1.21"

    bar.set_recent_saves([{"path": "C:/worlds/Recent", "name": "最近世界"}])
    action = bar._recent_menu.actions()[0]
    action.trigger()
    assert recent_paths == ["C:/worlds/Recent"]
    bar.deleteLater()
