"""View creation, caching and shell-host coordination."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, cast

import flet as ft

from app.models.responsive_layout import (
    ResponsiveLayout,
    resolve_responsive_layout,
)
from app.ui.components.buttons import McButton, btn_danger, btn_ghost
from app.ui.components.layout import PageHeader
from app.ui.theme import THEME
from app.ui.view_actions import ViewAction


LogCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class ViewHost:
    """应用壳层拥有、由 ViewManager 投影内容的控件。"""

    content: ft.Container


@dataclass(frozen=True)
class ViewManagerDependencies:
    """ViewManager 所需的显式应用能力端口。"""

    create_view: Callable[[str], ft.Control]
    get_current_save_path: Callable[[], Optional[str]]
    get_selected_view_id: Callable[[], Optional[str]]
    build_error_placeholder: Callable[[str, Exception], ft.Control]
    update_page: Callable[[], None]
    log: LogCallback
    translate: Callable[[str, str], str]
    get_top_actions: Callable[[str, ft.Control], Iterable[ViewAction]]


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
        self._current_actions: list[ViewAction] = []
        self._responsive_layout = resolve_responsive_layout(1100, 820)
        self._top_actions_enabled = True

    def attach_host(self, host: ViewHost) -> None:
        """在 Application 建好壳层后挂载内容区。

        Args:
            host: 壳层拥有的内容容器。
        """
        self._host = host

    def switch_view(self, view_id: str) -> None:
        """切换视图：按需创建、更新页面动作并同步当前存档。

        Args:
            view_id: 已注册的稳定视图标识。
        """
        try:
            host = self._require_host()
            if view_id not in self.views:
                self.views[view_id] = self.create_view(view_id)

            current_view = self.views[view_id]
            host.content.content = current_view
            self._update_top_actions(view_id, current_view)
            self._notify_view_layout(current_view)
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

    def _update_top_actions(
        self,
        view_id: str,
        current_view: ft.Control,
    ) -> None:
        self._require_host()
        self._current_actions = list(
            self._deps.get_top_actions(view_id, current_view)
        )
        self._rebuild_top_actions()

    def refresh_current_actions(self) -> None:
        """Refresh contextual commands after an in-view context change."""
        if self._host is None:
            return
        current_view = self._host.content.content
        view_id = self._deps.get_selected_view_id()
        if isinstance(current_view, ft.Control) and view_id is not None:
            self._update_top_actions(view_id, current_view)
            self._deps.update_page()

    def set_top_actions_enabled(self, enabled: bool) -> None:
        """启用或禁用当前页面标题栏动作按钮。

        未挂载宿主时为 no-op；单控件 ``update`` 失败（已拆卸）忽略。

        Args:
            enabled: True 启用，False 禁用。
        """
        self._top_actions_enabled = enabled
        action_row = self._current_action_row()
        if action_row is None:
            return
        for control in action_row.controls:
            control.disabled = not enabled
            try:
                control.update()
            except RuntimeError:
                pass

    def apply_compact_layout(self, compact: bool) -> None:
        """兼容旧调用方，以布尔值切换标准/紧凑布局。

        Args:
            compact: 是否进入紧凑布局。
        """
        width = 1000 if compact else 1200
        layout = resolve_responsive_layout(width, 820)
        ViewManager.apply_responsive_layout(self, layout)

    def apply_responsive_layout(self, layout: ResponsiveLayout) -> None:
        """调整页面动作尺寸并通知当前视图响应式配置。

        Args:
            layout: 当前窗口对应的响应式配置。
        """
        self._apply_top_action_layout(layout)

        view_id = self._deps.get_selected_view_id()
        current_view = self.views.get(view_id) if view_id else None
        self._notify_view_layout(current_view)

    def _notify_view_layout(self, current_view: Optional[ft.Control]) -> None:
        """Project the current responsive state to one view if supported."""
        responsive_callback = getattr(
            current_view,
            "set_responsive_layout",
            None,
        )
        if callable(responsive_callback):
            responsive_callback(self._responsive_layout)
            return
        callback = getattr(current_view, "set_compact_mode", None)
        if callable(callback):
            callback(self._responsive_layout.is_compact)

    def _apply_top_action_layout(self, layout: ResponsiveLayout) -> None:
        """Apply the layout and rebuild direct/overflow command projection."""
        self._responsive_layout = layout
        header = self._current_page_header()
        if header is not None:
            header.set_compact_layout(layout.is_compact)
        self._rebuild_top_actions()

    def _rebuild_top_actions(self) -> None:
        """Project commands without clipping labels in constrained layouts."""
        host_actions = self._current_action_row()
        if host_actions is None:
            return
        layout = self._responsive_layout
        direct_actions, overflow_actions = self._partition_top_actions(layout)
        host_actions.controls = [
            self._build_top_action_button(action, layout)
            for action in direct_actions
        ]
        if overflow_actions:
            host_actions.controls.append(
                self._build_overflow_menu(overflow_actions, layout)
            )
        host_actions.spacing = layout.action_spacing
        host_actions.visible = bool(self._current_actions)
        header = self._current_page_header()
        if header is not None:
            header.set_compact_layout(layout.is_compact)

    def _current_action_row(self) -> Optional[ft.Row]:
        """Return the current view's contextual page-header action row."""
        header = self._current_page_header()
        return header.action_row if header is not None else None

    def _current_page_header(self) -> Optional[PageHeader]:
        """Return the current view's page header when it exposes one."""
        if self._host is None:
            return None
        current_view = self._host.content.content
        header = getattr(current_view, "_page_header", None)
        if not isinstance(header, PageHeader):
            return None
        return header

    def _partition_top_actions(
        self,
        layout: ResponsiveLayout,
    ) -> tuple[list[ViewAction], list[ViewAction]]:
        """Split commands between the toolbar and its overflow menu."""
        limit = layout.visible_action_count
        if limit is None or len(self._current_actions) <= limit:
            return self._current_actions, []
        return self._current_actions[:limit], self._current_actions[limit:]

    def _build_top_action_button(
        self,
        action: ViewAction,
        layout: ResponsiveLayout,
    ) -> McButton:
        """Build one readable direct toolbar command."""
        preferred_width = max(86, min(140, len(action.label) * 14 + 28))
        builder = btn_danger if action.style == "danger" else btn_ghost
        button = builder(
            action.label,
            on_click=action.handler,
            width=min(preferred_width, layout.action_width_limit),
            height=layout.action_height,
        )
        button.disabled = not self._top_actions_enabled
        return button

    def _build_overflow_menu(
        self,
        actions: list[ViewAction],
        layout: ResponsiveLayout,
    ) -> ft.PopupMenuButton:
        """Build a full-label menu for commands that do not fit directly."""
        items = [
            ft.PopupMenuItem(
                content=ft.Text(
                    action.label,
                    color=(
                        THEME.error
                        if action.style == "danger"
                        else THEME.text_primary
                    ),
                ),
                on_click=self._adapt_menu_handler(action),
            )
            for action in actions
        ]
        return ft.PopupMenuButton(
            items=items,
            icon=ft.Icons.MORE_HORIZ,
            icon_color=THEME.text_secondary,
            tooltip=self._deps.translate(
                "top_bar.more_actions",
                "更多操作",
            ),
            width=40,
            height=layout.action_height,
            disabled=not self._top_actions_enabled,
        )

    @staticmethod
    def _adapt_menu_handler(
        action: ViewAction,
    ) -> Callable[[ft.Event[ft.PopupMenuItem]], None]:
        """Adapt the typed popup event to the existing view-action port."""
        def handle(event: ft.Event[ft.PopupMenuItem]) -> None:
            action.handler(cast(ft.ControlEvent, event))

        return handle

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
        """从缓存移除视图并释放其拥有的资源。

        Args:
            view_id: 视图标识。

        Returns:
            被移除的控件；不存在时为 None。
        """
        view = self.detach_view(view_id)
        if view is not None:
            self._dispose_view(view_id, view)
        return view

    def detach_view(self, view_id: str) -> Optional[ft.Control]:
        """从缓存分离视图，并将资源所有权转移给调用方。

        Args:
            view_id: 视图标识。

        Returns:
            被分离的控件；不存在时为 None。
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
            self._dispose_view(view_id, view)
        self.views.clear()

    def _dispose_view(self, view_id: str, view: ft.Control) -> None:
        dispose = getattr(view, "dispose", None)
        if not callable(dispose):
            return
        try:
            dispose()
        except Exception as error:
            self._deps.log(f"释放视图 '{view_id}' 失败: {error}", "ERROR")

    def _require_host(self) -> ViewHost:
        if self._host is None:
            raise RuntimeError("ViewManager 尚未挂载应用壳层")
        return self._host
