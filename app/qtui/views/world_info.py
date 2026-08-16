"""Qt Explorer 的存档信息投影面板。"""
from __future__ import annotations

from typing import Callable, Mapping, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.presenters.world_info_presenter import (
    InfoSection,
    build_world_info_sections,
)
from app.qtui.components.buttons import btn_ghost, btn_primary
from app.qtui.components.cards import card, divider, muted_label, section_title
from core.omni.models import WorldInfo


Translate = Callable[..., str]


class QtWorldInfoPanel(QScrollArea):
    """把框架中立的世界信息分区渲染为可选择文本。"""

    def __init__(
        self,
        translate: Translate,
        on_select_save: Callable[[], None],
        on_backup: Callable[[], None],
        on_restore: Callable[[], None],
    ) -> None:
        """构建存档信息面板。

        Args:
            translate: UI 翻译函数。
            on_select_save: 空状态选择存档命令。
            on_backup: 快速备份命令。
            on_restore: 打开备份中心命令。
        """
        super().__init__()
        self._t = translate
        self._on_select_save = on_select_save
        self._on_backup = on_backup
        self._on_restore = on_restore
        self._backup_button: QPushButton | None = None
        self.setWidgetResizable(True)
        self.show_empty()

    def show_empty(self) -> None:
        """显示尚未选择世界的空状态（图标 + 标题 + 副标题 + 按钮）。"""
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 40, 20, 40)
        layout.setSpacing(8)
        layout.addStretch(1)
        icon = QLabel("📦")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 44px;")
        layout.addWidget(icon)
        title = QLabel(self._t(
            "explorer.select_world_title",
            "请先设置当前存档以查看信息",
        ))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        subtitle = muted_label(self._t(
            "explorer.select_world_subtitle",
            "选择包含 level.dat 的 Minecraft 世界目录",
        ))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        select_button = btn_primary(
            f"📂  {self._t('explorer.load_world', '选择存档')}",
            on_click=self._on_select_save,
        )
        button_row = QWidget()
        button_layout = QHBoxLayout(button_row)
        button_layout.addStretch(1)
        button_layout.addWidget(select_button)
        button_layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(button_row)
        layout.addStretch(1)
        self._replace_widget(card(body, padding=0))

    def show_loading(self, message: str) -> None:
        """显示世界读取中的状态。"""
        label = muted_label(message)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addStretch(1)
        self._replace_widget(body)

    def show_info(
        self,
        world_info: Optional[WorldInfo],
        stats: Optional[Mapping[str, object]] = None,
    ) -> None:
        """显示世界信息分区和备份操作。"""
        if world_info is None:
            self._show_missing_info()
            return
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        sections = build_world_info_sections(world_info, stats, self._t)
        for section in sections:
            layout.addWidget(self._section_card(section))
        layout.addWidget(self._backup_card())
        layout.addStretch(1)
        self._replace_widget(body)

    def _show_missing_info(self) -> None:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addStretch(1)
        title = QLabel(self._t(
            "explorer.info_missing_title", "未找到存档信息"
        ))
        title.setProperty("role", "section")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = muted_label(self._t(
            "explorer.info_missing_subtitle",
            "该目录可能不是有效的 Minecraft 世界存档",
        ))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        self._replace_widget(body)

    def _section_card(self, section: InfoSection) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(section_title(section.title))
        layout.addWidget(divider())
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        for row_index, row in enumerate(section.rows):
            label = muted_label(row.label)
            label.setMinimumWidth(130)
            value = QLabel(row.value)
            value.setWordWrap(True)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card(body, padding=14)

    def _backup_card(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(section_title(self._t(
            "explorer.backup_title", "备份与恢复"
        )))
        layout.addWidget(divider())
        layout.addWidget(muted_label(self._t(
            "explorer.backup_subtitle",
            "创建恢复点或打开备份中心管理已有快照",
        )))
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 8, 0, 0)
        backup_button = btn_primary(
            self._t("explorer.create_backup", "创建备份"),
            on_click=self._on_backup,
        )
        self._backup_button = backup_button
        restore_button = btn_ghost(
            self._t("explorer.manage_backups", "管理恢复点"),
            on_click=self._on_restore,
        )
        row_layout.addWidget(backup_button)
        row_layout.addWidget(restore_button)
        row_layout.addStretch(1)
        layout.addWidget(row)
        return card(body, padding=14)

    def set_backup_busy(self, busy: bool) -> None:
        """设置快速备份按钮忙碌状态。"""
        if self._backup_button is not None:
            self._backup_button.setEnabled(not busy)

    def _replace_widget(self, widget: QWidget) -> None:
        previous = self.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self._backup_button = None
        self.setWidget(widget)


__all__ = ["QtWorldInfoPanel"]
