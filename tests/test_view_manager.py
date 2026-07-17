"""Tests for ViewManager's explicit shell boundary."""
import flet as ft

from app.core.view_manager import (
    ViewHost,
    ViewManager,
    ViewManagerDependencies,
)
from app.ui.view_actions import ViewAction


class ActionView(ft.Column):
    def __init__(self) -> None:
        super().__init__()
        self.selected_paths = []
        self.command_calls = 0

    def get_top_actions(self) -> list[ViewAction]:
        return [ViewAction("执行", self._execute)]

    def _execute(self, event=None) -> None:
        self.command_calls += 1

    def on_save_selected(self, path: str) -> None:
        self.selected_paths.append(path)


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
    ))
    content = ft.Container()
    actions = ft.Row()
    manager.attach_host(ViewHost(content, actions))
    return manager, content, actions, updates, logs


def test_view_manager_projects_view_actions_and_save_context() -> None:
    view = ActionView()
    manager, content, actions, updates, logs = _manager(
        lambda view_id: view
    )

    manager.switch_view("test")

    assert content.content is view
    assert len(actions.controls) == 1
    assert actions.visible is True
    assert view.selected_paths == ["C:/world"]
    assert updates == ["update"]
    assert logs == []

    manager.set_top_actions_enabled(False)
    assert actions.controls[0].disabled is True

    manager.notify_current_view_save_selected("D:/other")
    assert view.selected_paths[-1] == "D:/other"


def test_view_manager_renders_factory_errors_without_application_access() -> None:
    def fail(view_id: str) -> ft.Control:
        raise RuntimeError("factory failed")

    manager, content, actions, updates, logs = _manager(fail)

    manager.switch_view("broken")

    assert isinstance(content.content, ft.Text)
    assert "factory failed" in str(content.content.value)
    assert updates == ["update"]
    assert logs[-1][1] == "ERROR"
    assert actions.controls == []


def test_view_manager_cache_has_explicit_accessors() -> None:
    view = ActionView()
    manager, _, _, _, _ = _manager(lambda view_id: view)
    manager.switch_view("test")

    assert manager.get_view("test") is view
    assert manager.remove_view("test") is view
    assert manager.get_view("test") is None
