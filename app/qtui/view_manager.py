"""Qt 视图管理器：惰性创建、切换、释放（对应 Flet 版 ``app/core/view_manager.py``）。"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtWidgets import QStackedWidget, QWidget

from app.qtui.animation import QtAnimationSystem
from app.qtui.context import QtFeatureContext
from app.qtui.registry import QtFeatureRegistry
from app.qtui.view_actions import QtViewAction

ViewFactory = Callable[[QtFeatureContext], QWidget]


class QtViewManager:
    """在 QStackedWidget 中托管 Qt 视图。

    视图按需创建；切换时触发 ``on_view_changed``（用于顶栏动作与侧边栏刷新）。
    移除视图时调用幂等 ``dispose()``（若存在）。
    """

    def __init__(
        self,
        *,
        registry: QtFeatureRegistry,
        stack: QStackedWidget,
        context: QtFeatureContext,
        animations: Optional[QtAnimationSystem] = None,
        on_view_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        """构建视图管理器。

        Args:
            registry: 功能注册表（工厂来源）。
            stack: 承载视图的 QStackedWidget。
            context: 传给所有视图的端口包。
            animations: 可选的全局动效系统。
            on_view_changed: 视图切换回调（view_id）。
        """
        self._registry = registry
        self._stack = stack
        self._context = context
        self._animations = animations
        self._on_view_changed = on_view_changed
        self._views: dict[str, QWidget] = {}
        self._current_id: Optional[str] = None

    @property
    def current_view_id(self) -> Optional[str]:
        """返回当前视图 id。"""
        return self._current_id

    def get_view(self, view_id: str) -> Optional[QWidget]:
        """返回已创建视图；未创建返回 None。"""
        return self._views.get(view_id)

    def switch_view(self, view_id: str) -> None:
        """切换（并按需创建）指定视图。"""
        if view_id == self._current_id:
            return
        view = self._views.get(view_id)
        if view is None:
            view = self._create_view(view_id)
        is_initial_view = self._current_id is None
        self._stack.setCurrentWidget(view)
        self._current_id = view_id
        if self._animations is not None and not is_initial_view:
            self._animations.fade_in(view)
        if self._on_view_changed is not None:
            self._on_view_changed(view_id)

    def remove_view(self, view_id: str) -> None:
        """释放并移除指定视图（幂等）。"""
        view = self._views.pop(view_id, None)
        if view is None:
            return
        if self._animations is not None:
            self._animations.stop(view)
        self._dispose_view(view)
        self._stack.removeWidget(view)
        view.deleteLater()
        if self._current_id == view_id:
            self._current_id = None

    def get_top_actions(self, view_id: str) -> list[QtViewAction]:
        """返回视图暴露的顶栏动作（按需创建视图）。"""
        view = self._views.get(view_id)
        if view is None:
            view = self._create_view(view_id)
        provider = getattr(view, "get_top_actions", None)
        if not callable(provider):
            return []
        actions = provider()
        if not isinstance(actions, list):
            return []
        return actions

    def apply_responsive_layout(self, layout: str) -> None:
        """应用响应式布局模式（Qt 骨架暂为无操作占位）。"""
        del layout

    def notify_save_selected(self, path: str) -> None:
        """通知全部已创建视图：当前存档已切换。"""
        for view in tuple(self._views.values()):
            handler = getattr(view, "on_save_selected", None)
            if callable(handler):
                handler(path)

    def notify_save_cleared(self) -> None:
        """通知全部已创建视图：当前存档已清空。"""
        for view in tuple(self._views.values()):
            handler = getattr(view, "on_save_cleared", None)
            if callable(handler):
                handler()

    def refresh_theme(self) -> None:
        """通知已创建视图刷新主题相关的局部样式。"""
        for view in tuple(self._views.values()):
            handler = getattr(view, "refresh_theme", None)
            if callable(handler):
                handler()

    def dispose_all(self) -> None:
        """释放全部视图（窗口关闭时调用）。"""
        if self._animations is not None:
            self._animations.stop_all()
        for view_id, view in self._views.items():
            self._dispose_view(view)
        self._views.clear()
        self._current_id = None

    # ─── 内部 ────────────────────────────────────

    def _create_view(self, view_id: str) -> QWidget:
        feature = self._registry.get(view_id)
        if feature is None:
            raise KeyError(f"未注册的 Qt 视图: {view_id}")
        view = feature.factory(self._context)
        self._views[view_id] = view
        self._stack.addWidget(view)
        did_mount = getattr(view, "did_mount", None)
        if callable(did_mount):
            did_mount()
        return view

    @staticmethod
    def _dispose_view(view: QWidget) -> None:
        dispose = getattr(view, "dispose", None)
        if callable(dispose):
            dispose()
