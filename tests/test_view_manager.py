"""Tests for ViewManager's explicit shell boundary."""
import flet as ft

from app.core.view_manager import (
    ViewHost,
    ViewManager,
    ViewManagerDependencies,
)
from app.models.responsive_layout import resolve_responsive_layout
from app.ui.components.buttons import McButton
from app.ui.components.layout import page_header
from app.ui.icons import IconSet
from app.ui.theme import THEME
from app.ui.view_actions import ViewAction


class ActionView(ft.Column):
    def __init__(self) -> None:
        super().__init__()
        self._page_header = page_header(
            "测试页面",
            ft.Text("测试命令"),
            icon=IconSet.BUILD,
        )
        self.controls = [self._page_header]
        self.selected_paths = []
        self.command_calls = 0
        self.compact_modes = []

    def get_top_actions(self) -> list[ViewAction]:
        return [ViewAction("执行", self._execute)]

    def _execute(self, event=None) -> None:
        self.command_calls += 1

    def on_save_selected(self, path: str) -> None:
        self.selected_paths.append(path)

    def set_compact_mode(self, compact: bool) -> None:
        self.compact_modes.append(compact)


class ManyActionView(ActionView):
    def get_top_actions(self) -> list[ViewAction]:
        return [
            ViewAction(f"命令 {index}", self._execute)
            for index in range(7)
        ]


def _manager(create_view, selected=lambda: "test"):
    updates = []
    logs = []
    manager = ViewManager(ViewManagerDependencies(
        create_view=create_view,
        get_current_save_path=lambda: "C:/world",
        get_selected_view_id=selected,
        build_error_placeholder=lambda view_id, error: ft.Text(
            f"{view_id}: {error}"
        ),
        update_page=lambda: updates.append("update"),
        log=lambda message, level: logs.append((message, level)),
        translate=lambda key, default: default,
    ))
    content = ft.Container()
    manager.attach_host(ViewHost(content))
    return manager, content, updates, logs


def test_view_manager_projects_view_actions_and_save_context() -> None:
    view = ActionView()
    manager, content, updates, logs = _manager(
        lambda view_id: view
    )

    manager.switch_view("test")

    actions = view._page_header.action_row
    assert content.content is view
    assert len(actions.controls) == 1
    assert actions.visible is True
    action_button = actions.controls[0]
    assert isinstance(action_button, McButton)
    assert action_button.bgcolor == THEME.bg_elevated
    assert view.selected_paths == ["C:/world"]
    assert updates == ["update"]
    assert logs == []

    manager.set_top_actions_enabled(False)
    assert actions.controls[0].disabled is True

    manager.apply_compact_layout(True)
    assert actions.spacing == 5
    assert getattr(actions.controls[0], "height") == 44
    assert isinstance(view._page_header.content, ft.Column)
    assert view.compact_modes == [False, True]

    manager.apply_responsive_layout(resolve_responsive_layout(1400, 820))
    assert actions.spacing == 8
    assert getattr(actions.controls[0], "height") == 44
    assert getattr(actions.controls[0], "width") == 86
    assert isinstance(view._page_header.content, ft.Row)
    assert view.compact_modes[-1] is False

    manager.notify_current_view_save_selected("D:/other")
    assert view.selected_paths[-1] == "D:/other"


def test_narrow_toolbar_moves_extra_commands_into_full_label_menu() -> None:
    view = ManyActionView()
    manager, _, _, _ = _manager(lambda view_id: view)
    manager.switch_view("test")
    actions = view._page_header.action_row

    manager.apply_responsive_layout(resolve_responsive_layout(800, 600))

    assert len(actions.controls) == 3
    assert all(
        isinstance(control, McButton)
        for control in actions.controls[:2]
    )
    first_action = actions.controls[0]
    assert isinstance(first_action, McButton)
    assert first_action.width == 86
    overflow = actions.controls[-1]
    assert isinstance(overflow, ft.PopupMenuButton)
    assert len(overflow.items) == 5
    assert isinstance(overflow.items[0].content, ft.Text)
    assert overflow.items[0].content.value == "命令 2"

    manager.apply_responsive_layout(resolve_responsive_layout(1400, 820))

    assert len(actions.controls) == 7
    assert all(isinstance(control, McButton) for control in actions.controls)


def test_refresh_current_actions_updates_the_mounted_page() -> None:
    view = ActionView()
    manager, _, updates, _ = _manager(lambda view_id: view)
    manager.switch_view("test")

    manager.refresh_current_actions()

    assert updates == ["update", "update"]


def test_view_manager_renders_factory_errors_without_application_access() -> None:
    def fail(view_id: str) -> ft.Control:
        raise RuntimeError("factory failed")

    manager, content, updates, logs = _manager(fail)

    manager.switch_view("broken")

    assert isinstance(content.content, ft.Text)
    assert "factory failed" in str(content.content.value)
    assert updates == ["update"]
    assert logs[-1][1] == "ERROR"


def test_view_manager_cache_has_explicit_accessors() -> None:
    view = ActionView()
    manager, _, _, _ = _manager(lambda view_id: view)
    manager.switch_view("test")

    assert manager.get_view("test") is view
    assert manager.remove_view("test") is view
    assert manager.get_view("test") is None
