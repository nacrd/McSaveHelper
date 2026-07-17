"""侧边栏公开行为与 Flet 0.85 事件回归。"""
from app.ui.icons import IconSet
from app.ui.sidebar import Sidebar


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
