"""Qt 应用壳层：顶栏动作 + 侧边栏 + 内容堆栈 + 状态栏。

壳层是普通 QWidget（由组合根设为 QMainWindow 的中央控件），
状态栏以布局嵌入底部，而不是 QMainWindow 的 setStatusBar。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.qtui.progress import QtProgressHost
from app.qtui.sidebar import QtSidebar
from app.qtui.view_actions import QtViewAction
from app.qtui.world_context_bar import QtWorldContextBar

Translate = Callable[..., str]


class QtShell(QWidget):
    """主窗口壳层（可嵌入 QMainWindow 的中央区域）。

    结构：顶栏（标题 + 视图动作） / 主体（侧边栏 + QStackedWidget） / 状态栏。
    """

    def __init__(
        self,
        *,
        translate: Translate,
        sidebar: QtSidebar,
        view_stack: QStackedWidget,
        on_view_action: Callable[[QtViewAction], None],
        on_pick_world: Callable[[], None],
        on_recent_world: Callable[[str], None],
        on_quick_backup: Callable[[], None],
    ) -> None:
        """构建壳层。

        Args:
            translate: 翻译函数。
            sidebar: 侧边栏控件。
            view_stack: 视图堆栈。
            on_view_action: 顶栏动作点击回调。
            on_pick_world: 选择当前世界回调。
            on_recent_world: 最近世界选择回调。
            on_quick_backup: 快速备份回调。
        """
        super().__init__()
        self._translate = translate
        self._on_view_action = on_view_action
        self._action_buttons: list[QPushButton] = []

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 布局：固定世界上下文栏，右侧承载当前页面主动作。
        top_bar = QWidget()
        top_bar.setObjectName("top_bar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 8, 0)
        top_layout.setSpacing(8)
        self._world_context = QtWorldContextBar(
            translate=translate,
            on_pick_world=on_pick_world,
            on_recent_world=on_recent_world,
            on_quick_backup=on_quick_backup,
        )
        top_layout.addWidget(self._world_context, 1)
        self._action_host = QWidget()
        self._action_layout = QHBoxLayout(self._action_host)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(6)
        top_layout.addWidget(self._action_host)
        root_layout.addWidget(top_bar)

        # 主体
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(sidebar)
        body_layout.addWidget(view_stack, 1)
        root_layout.addWidget(body, 1)

        # 状态栏 + 进度（以布局嵌入）
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(False)
        root_layout.addWidget(self._status_bar)
        self._progress = QtProgressHost(self._status_bar)

    @property
    def progress(self) -> QtProgressHost:
        """返回进度宿主。"""
        return self._progress

    def set_current_save(
        self,
        path: Optional[str],
        *,
        status: str = "ready",
        detail: str = "",
    ) -> None:
        """更新固定世界上下文。"""
        self._world_context.set_current_save(
            path,
            status=status,
            detail=detail,
        )

    def set_world_status(self, status: str, detail: str = "") -> None:
        """更新当前世界的加载或错误状态。"""
        self._world_context.set_status(status, detail)

    def set_recent_saves(self, saves: list[dict[str, object]]) -> None:
        """更新世界上下文栏中的最近世界菜单。"""
        self._world_context.set_recent_saves(saves)

    def set_view_actions(self, actions: list[QtViewAction]) -> None:
        """重建顶栏视图动作按钮。"""
        for button in self._action_buttons:
            self._action_layout.removeWidget(button)
            button.deleteLater()
        self._action_buttons.clear()
        for action in actions:
            button = QPushButton(action.label)
            if action.style == "danger":
                button.setProperty("role", "danger")
            else:
                button.setProperty("role", "primary")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setEnabled(action.enabled)
            button.clicked.connect(
                lambda _checked, act=action: self._on_view_action(act)
            )
            self._action_buttons.append(button)
            self._action_layout.addWidget(button)

    def clear_view_actions(self) -> None:
        """清空顶栏动作。"""
        self.set_view_actions([])

    def set_action_enabled(self, label: str, enabled: bool) -> None:
        """按完整标签设置当前顶栏动作状态。"""
        for button in self._action_buttons:
            if button.text() == label:
                button.setEnabled(enabled)

    def show_status_message(self, message: str, timeout_ms: int = 5000) -> None:
        """在状态栏显示一条自动消失的非阻塞消息。"""
        self._status_bar.showMessage(message, timeout_ms)
