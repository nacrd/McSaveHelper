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
    """应用壳层拥有、由 ViewManager 投影内容的控件。"""

    content: ft.Container
    top_actions: ft.Row


@dataclass(frozen=True)
class ViewManagerDependencies:
    """ViewManager 所需的显式应用能力端口。"""

    create_view: Callable[[str], ft.Control]
    get_current_save_path: Callable[[], Optional[str]]
    get_selected_view_id: Callable[[], Optional[str]]
    build_error_placeholder: Callable[[str, Exception], ft.Control]
    update_page: Callable[[], None]
    log: LogCallback


class ViewManager:
    """创建并缓存视图，投影到已挂载的壳层宿主。

    应用关闭时应调用 :meth:`dispose` 幂等释放持有后台资源的视图。
    """

    def __init__(self, dependencies: ViewManagerDependencies) -> None:
        """绑定应用能力端口。

        Args:
            dependencies: 建视图、取路径/选中项、占位与日志等依赖。
        """
        self._deps = dependencies
        self._host: Optional[ViewHost] = None
        self.views: Dict[str, ft.Control] = {}

    def attach_host(self, host: ViewHost) -> None:
        """在 Application 建好壳层后挂载内容区与顶部动作行。

        Args:
            host: 壳层拥有的内容容器与顶部按钮行。
        """
        self._host = host

    def switch_view(self, view_id: str) -> None:
        """切换到指定视图：按需创建、更新顶部动作并同步当前存档。

        Args:
            view_id: 已注册的稳定视图标识。
        """
        try:
            host = self._require_host()
            if view_id not in self.views:
                self.views[view_id] = self.create_view(view_id)

            current_view = self.views[view_id]
            host.content.content = current_view
            self._update_top_actions(current_view)
            self._notify_save_selected(current_view)
            self._deps.update_page()
        except (RuntimeError, TypeError, AttributeError, ValueError) as error:
            self._deps.log(f"加载视图 '{view_id}' 失败: {error}", "ERROR")
            self._handle_view_error(view_id, error)
        except Exception as error:
            # View factories/UI may raise Flet-specific errors.
            self._deps.log(f"加载视图 '{view_id}' 失败: {error}", "ERROR")
            self._handle_view_error(view_id, error)

    def create_view(self, view_id: str) -> ft.Control:
        """通过工厂创建视图并校验返回类型。

        Args:
            view_id: 视图标识。

        Returns:
            新建的 Flet Control。

        Raises:
            TypeError: 工厂未返回 ``ft.Control``。
        """
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
        """启用或禁用壳层顶部动作按钮。

        未挂载宿主时为 no-op；单控件 ``update`` 失败（已拆卸）忽略。

        Args:
            enabled: True 启用，False 禁用。
        """
        if self._host is None:
            return
        for control in self._host.top_actions.controls:
            control.disabled = not enabled
            try:
                control.update()
            except RuntimeError:
                pass

    def apply_compact_layout(self, compact: bool) -> None:
        """调整壳层动作尺寸并通知当前视图紧凑模式。

        Args:
            compact: 是否进入紧凑布局。
        """
        if self._host is not None:
            self._host.top_actions.spacing = 6 if compact else 8
            for button in self._host.top_actions.controls:
                if hasattr(button, "height"):
                    setattr(button, "height", 34 if compact else 38)
                if hasattr(button, "width") and compact:
                    width = getattr(button, "width", 120) or 120
                    setattr(button, "width", min(width, 104))

        view_id = self._deps.get_selected_view_id()
        current_view = self.views.get(view_id) if view_id else None
        callback = getattr(current_view, "set_compact_mode", None)
        if callable(callback):
            callback(compact)

    def _notify_save_selected(self, view: ft.Control) -> None:
        current_save_path = self._deps.get_current_save_path()
        callback = getattr(view, "on_save_selected", None)
        if not current_save_path or not callable(callback):
            return
        try:
            callback(current_save_path)
        except Exception as error:
            # View callbacks may raise UI/runtime errors; isolate them.
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
            # Last-resort UI fallback when page is already torn down.
            pass

    def notify_current_view_save_selected(self, path: str) -> None:
        """将当前存档路径通知给已选中视图。

        Args:
            path: 新的当前存档展示路径。
        """
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
        """从缓存移除视图但不调用 dispose。

        Args:
            view_id: 视图标识。

        Returns:
            被移除的控件；不存在时为 None。
        """
        return self.views.pop(view_id, None)

    def get_view(self, view_id: str) -> Optional[ft.Control]:
        """按标识取已缓存视图。

        Args:
            view_id: 视图标识。

        Returns:
            缓存中的控件；未创建时为 None。
        """
        return self.views.get(view_id)

    def dispose(self) -> None:
        """对缓存中支持 dispose 的视图逐个幂等释放并清空缓存。"""
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
