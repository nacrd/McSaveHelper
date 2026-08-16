"""固定世界上下文栏：当前世界、最近世界与安全快捷入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.qtui.icons import glyph

Translate = Callable[..., str]


class QtWorldContextBar(QFrame):
    """在所有页面持续展示当前世界和直接操作。"""

    def __init__(
        self,
        *,
        translate: Translate,
        on_pick_world: Callable[[], None],
        on_recent_world: Callable[[str], None],
        on_quick_backup: Callable[[], None],
    ) -> None:
        """构建世界上下文栏。

        Args:
            translate: UI 翻译函数。
            on_pick_world: 选择或切换世界回调。
            on_recent_world: 最近世界选择回调。
            on_quick_backup: 为当前世界创建快速备份的回调。
        """
        super().__init__()
        self.setObjectName("world_context_bar")
        self._translate = translate
        self._on_recent_world = on_recent_world
        self._world_path = ""
        self._build(on_pick_world, on_quick_backup)
        self.set_current_save(None)

    def _build(
        self,
        on_pick_world: Callable[[], None],
        on_quick_backup: Callable[[], None],
    ) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        icon = QLabel(glyph("SAVE"))
        icon.setObjectName("world_context_icon")
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        labels = QWidget()
        labels.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        labels_layout = QVBoxLayout(labels)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(0)
        self._world_name = QLabel()
        self._world_name.setObjectName("world_context_name")
        self._world_detail = QLabel()
        self._world_detail.setProperty("role", "muted")
        labels_layout.addWidget(self._world_name)
        labels_layout.addWidget(self._world_detail)
        layout.addWidget(labels, 1)

        self._status = QLabel()
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setMinimumWidth(64)
        layout.addWidget(self._status)

        self._recent_button = QToolButton()
        self._recent_button.setText(self._t(
            "workspace.recent_worlds", "最近世界"
        ))
        self._recent_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._recent_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self._recent_menu = QMenu(self._recent_button)
        self._recent_button.setMenu(self._recent_menu)
        layout.addWidget(self._recent_button)

        self._pick_button = QPushButton(
            f"{glyph('FOLDER_OPEN')}  "
            f"{self._t('workspace.switch_world', '切换世界')}"
        )
        self._pick_button.setProperty("role", "ghost")
        self._pick_button.clicked.connect(lambda: on_pick_world())
        layout.addWidget(self._pick_button)

        self._backup_button = QPushButton(
            f"{glyph('SAVE')}  "
            f"{self._t('workspace.quick_backup', '快速备份')}"
        )
        self._backup_button.setProperty("role", "primary")
        self._backup_button.clicked.connect(lambda: on_quick_backup())
        layout.addWidget(self._backup_button)

    def set_current_save(
        self,
        path: str | None,
        *,
        status: str = "ready",
        detail: str = "",
    ) -> None:
        """更新当前世界展示。

        Args:
            path: 当前世界路径；未选择时为 None。
            status: ``required``、``loading``、``ready`` 或 ``error``。
            detail: 世界版本、加载阶段或错误摘要。
        """
        self._world_path = path or ""
        if not path:
            self._world_name.setText(self._t(
                "workspace.no_world", "未设置当前世界"
            ))
            self._world_detail.setText(self._t(
                "workspace.select_world_hint",
                "选择包含 level.dat 的 Minecraft Java 世界目录",
            ))
            self._world_name.setToolTip("")
            self._backup_button.setEnabled(False)
            self._pick_button.setProperty("role", "primary")
            self._refresh_button_style(self._pick_button)
            self.set_status("required")
            return

        world_path = Path(path)
        self._world_name.setText(world_path.name or str(world_path))
        self._world_name.setToolTip(str(world_path))
        self._world_detail.setText(detail or self._t(
            "workspace.java_world", "Minecraft Java 世界"
        ))
        self._backup_button.setEnabled(True)
        self._pick_button.setProperty("role", "ghost")
        self._refresh_button_style(self._pick_button)
        self.set_status(status)

    def set_status(self, status: str, detail: str = "") -> None:
        """更新世界状态徽标和可选详情。"""
        labels = {
            "required": self._t("workspace.status_required", "需要选择"),
            "loading": self._t("workspace.status_loading", "加载中"),
            "ready": self._t("workspace.status_ready", "已就绪"),
            "error": self._t("workspace.status_error", "不可用"),
        }
        normalized = status if status in labels else "ready"
        self._status.setText(labels[normalized])
        self._status.setProperty("contextStatus", normalized)
        self._refresh_button_style(self._status)
        if detail:
            self._world_detail.setText(detail)

    def set_recent_saves(
        self,
        saves: Sequence[Mapping[str, object]],
    ) -> None:
        """重建最近世界菜单。

        Args:
            saves: 含 ``path`` 和可选 ``name`` 的最近世界条目。
        """
        self._recent_menu.clear()
        valid_count = 0
        for save in saves:
            path = save.get("path")
            if not isinstance(path, str) or not path:
                continue
            name = save.get("name")
            label = name if isinstance(name, str) and name else Path(path).name
            action = QAction(label or path, self._recent_menu)
            action.setToolTip(path)
            action.triggered.connect(
                lambda _checked=False, selected=path: self._on_recent_world(selected)
            )
            self._recent_menu.addAction(action)
            valid_count += 1
        if valid_count:
            self._recent_button.setEnabled(True)
            return
        empty = self._recent_menu.addAction(self._t(
            "workspace.no_recent_worlds", "暂无最近世界"
        ))
        empty.setEnabled(False)
        self._recent_button.setEnabled(False)

    def _t(self, key: str, default: str) -> str:
        return self._translate(key, default)

    @staticmethod
    def _refresh_button_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()


__all__ = ["QtWorldContextBar"]
