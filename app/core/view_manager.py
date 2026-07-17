"""View creation, caching and shell-host coordination."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, cast

import flet as ft

from app.ui.components.buttons import btn_danger, btn_primary
from app.ui.theme import THEME
from app.ui.view_actions import ViewAction


LogCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class ViewHost:
    """Controls owned by the application shell and rendered by ViewManager."""

    content: ft.Container
    top_actions: ft.Row


@dataclass(frozen=True)
class ViewManagerDependencies:
    """Explicit application capabilities required by ViewManager."""

    create_view: Callable[[str], ft.Control]
    get_current_save_path: Callable[[], Optional[str]]
    get_selected_view_id: Callable[[], Optional[str]]
    build_error_placeholder: Callable[[str, Exception], ft.Control]
    update_page: Callable[[], None]
    log: LogCallback


class ViewManager:
    """Create cached views and project them into an attached shell host."""

    def __init__(self, dependencies: ViewManagerDependencies) -> None:
        self._deps = dependencies
        self._host: Optional[ViewHost] = None
        self.views: Dict[str, ft.Control] = {}

    def attach_host(self, host: ViewHost) -> None:
        """Attach shell controls after Application has constructed its UI."""
        self._host = host

    def switch_view(self, view_id: str) -> None:
        try:
            host = self._require_host()
            if view_id not in self.views:
                self.views[view_id] = self.create_view(view_id)

            current_view = self.views[view_id]
            host.content.content = current_view
            self._update_top_actions(current_view)
            self._notify_save_selected(current_view)
            self._deps.update_page()
        except Exception as error:
            self._deps.log(f"加载视图 '{view_id}' 失败: {error}", "ERROR")
            self._handle_view_error(view_id, error)

    def create_view(self, view_id: str) -> ft.Control:
        view = self._deps.create_view(view_id)
        if not isinstance(view, ft.Control):
            raise TypeError(f"视图工厂未返回 Flet Control: {view_id}")
        return view

    def _update_top_actions(self, current_view: ft.Control) -> None:
        host = self._require_host()
        provider = getattr(current_view, "get_top_actions", None)
        actions = (
            list(cast(Iterable[ViewAction], provider()))
            if callable(provider)
            else []
        )
        host.top_actions.controls.clear()

        for action in actions:
            width = max(86, min(140, len(action.label) * 14 + 28))
            builder = btn_danger if action.style == "danger" else btn_primary
            host.top_actions.controls.append(builder(
                action.label,
                on_click=action.handler,
                width=width,
                height=38,
            ))
        host.top_actions.visible = bool(actions)

    def set_top_actions_enabled(self, enabled: bool) -> None:
        if self._host is None:
            return
        for control in self._host.top_actions.controls:
            control.disabled = not enabled
            try:
                control.update()
            except RuntimeError:
                pass

    def _notify_save_selected(self, view: ft.Control) -> None:
        current_save_path = self._deps.get_current_save_path()
        callback = getattr(view, "on_save_selected", None)
        if not current_save_path or not callable(callback):
            return
        try:
            callback(current_save_path)
        except Exception as error:
            self._deps.log(f"同步当前存档失败: {error}", "ERROR")

    def _handle_view_error(self, view_id: str, error: Exception) -> None:
        if self._host is None:
            return
        try:
            self._host.content.content = self._deps.build_error_placeholder(
                view_id,
                error,
            )
            self._deps.update_page()
        except Exception:
            self._show_simple_error(view_id, error)

    def _show_simple_error(self, view_id: str, error: Exception) -> None:
        if self._host is None:
            return
        try:
            self._host.content.content = ft.Container(
                content=ft.Text(
                    f"加载页面 '{view_id}' 时出错: {error}",
                    color=THEME.error,
                    size=14,
                ),
                padding=40,
            )
            self._deps.update_page()
        except Exception:
            pass

    def notify_current_view_save_selected(self, path: str) -> None:
        view_id = self._deps.get_selected_view_id()
        current_view = self.views.get(view_id) if view_id else None
        callback = getattr(current_view, "on_save_selected", None)
        if not callable(callback):
            return
        try:
            callback(path)
        except Exception as error:
            self._deps.log(f"通知视图失败: {error}", "ERROR")

    def remove_view(self, view_id: str) -> Optional[ft.Control]:
        return self.views.pop(view_id, None)

    def get_view(self, view_id: str) -> Optional[ft.Control]:
        return self.views.get(view_id)

    def dispose(self) -> None:
        for view_id, view in tuple(self.views.items()):
            dispose = getattr(view, "dispose", None)
            if not callable(dispose):
                continue
            try:
                dispose()
            except Exception as error:
                self._deps.log(f"释放视图 '{view_id}' 失败: {error}", "ERROR")
        self.views.clear()

    def _require_host(self) -> ViewHost:
        if self._host is None:
            raise RuntimeError("ViewManager 尚未挂载应用壳层")
        return self._host
