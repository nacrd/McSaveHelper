"""Qt Explorer 的 NBT 文档与暂存审阅面板。"""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.nbt_edit import NbtChange, NbtPath
from app.presenters.nbt_tree import format_nbt_value
from app.qtui.views.nbt_tree import QtNbtTree
from app.services.nbt_document_service import (
    LoadedNbtDocument,
    NbtDocumentTarget,
)


Translate = Callable[..., str]
Command = Callable[[], None]
StageChange = Callable[[NbtPath, object, object, str], None]


class QtNbtPanel(QWidget):
    """NBT 目标选择、惰性树和暂存变更审阅面板。"""

    _INDEX_ROLE = int(Qt.ItemDataRole.UserRole)

    def __init__(
        self,
        translate: Translate,
        on_load: Command,
        on_reload: Command,
        on_stage: StageChange,
        on_remove: Command,
        on_discard: Command,
        on_commit: Command,
    ) -> None:
        """构建 NBT 工作区并绑定命令。

        Args:
            translate: UI 翻译回调。
            on_load: 选择目标后的加载命令。
            on_reload: 重载当前目标命令。
            on_stage: 树叶子值暂存命令。
            on_remove: 撤销选中暂存项命令。
            on_discard: 丢弃全部暂存项命令。
            on_commit: 提交全部暂存项命令。
        """
        super().__init__()
        self._translate = translate
        self._has_world = False
        self._busy = False
        self._build(on_load, on_reload, on_stage, on_remove, on_discard, on_commit)
        self.show_world(False)

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def _build(
        self,
        on_load: Command,
        on_reload: Command,
        on_stage: StageChange,
        on_remove: Command,
        on_discard: Command,
        on_commit: Command,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._tree = QtNbtTree(self._translate, on_stage)
        layout.addLayout(self._build_toolbar(on_load, on_reload))
        self._status = QLabel()
        self._status.setProperty("role", "muted")
        layout.addWidget(self._status)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._build_stage_panel(on_remove, on_discard, on_commit))
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes((680, 420))
        layout.addWidget(splitter, 1)

    def _build_toolbar(self, on_load: Command, on_reload: Command) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(self._t("nbt_editor.target", "目标")))
        self._targets = QComboBox()
        self._targets.setMinimumWidth(260)
        self._targets.activated.connect(lambda _index: on_load())
        row.addWidget(self._targets, 1)
        self._reload = QPushButton(self._t("nbt_editor.reload", "重新加载"))
        self._reload.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_BrowserReload
        ))
        self._reload.clicked.connect(lambda _checked: on_reload())
        row.addWidget(self._reload)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(self._t(
            "nbt_editor.filter_hint", "筛选已展开的节点"
        ))
        self._filter.textChanged.connect(self._tree.filter_items)
        row.addWidget(self._filter, 1)
        return row

    def _build_stage_panel(
        self,
        on_remove: Command,
        on_discard: Command,
        on_commit: Command,
    ) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)
        title_row = QHBoxLayout()
        self._stage_status = QLabel()
        title_row.addWidget(self._stage_status, 1)
        layout.addLayout(title_row)
        self._stages = QTableWidget(0, 4)
        self._stages.setHorizontalHeaderLabels((
            self._t("nbt_editor.column_path", "路径"),
            self._t("nbt_editor.column_old", "原值"),
            self._t("nbt_editor.column_new", "新值"),
            self._t("nbt_editor.column_format", "格式"),
        ))
        self._stages.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._stages.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._stages.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._stages.verticalHeader().setVisible(False)
        header = self._stages.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._stages.itemSelectionChanged.connect(self._update_actions)
        layout.addWidget(self._stages, 1)
        actions = QHBoxLayout()
        self._remove = QPushButton(self._t("nbt_editor.unstage", "撤销选中"))
        self._remove.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_TrashIcon
        ))
        self._remove.clicked.connect(lambda _checked: on_remove())
        actions.addWidget(self._remove)
        actions.addStretch(1)
        self._discard = QPushButton(self._t("nbt_editor.discard", "全部丢弃"))
        self._discard.setProperty("role", "danger")
        self._discard.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_DialogDiscardButton
        ))
        self._discard.clicked.connect(lambda _checked: on_discard())
        actions.addWidget(self._discard)
        self._commit = QPushButton(self._t("nbt_editor.commit", "提交变更"))
        self._commit.setProperty("role", "primary")
        self._commit.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_DialogApplyButton
        ))
        self._commit.clicked.connect(lambda _checked: on_commit())
        actions.addWidget(self._commit)
        layout.addLayout(actions)
        return panel

    @property
    def selected_target(self) -> NbtDocumentTarget | None:
        """返回目标下拉框中的类型化目标。"""
        target = self._targets.currentData()
        return target if isinstance(target, NbtDocumentTarget) else None

    @property
    def selected_stage_index(self) -> int | None:
        """返回暂存表当前行对应的全局索引。"""
        row = self._stages.currentRow()
        item = self._stages.item(row, 0) if row >= 0 else None
        index = item.data(self._INDEX_ROLE) if item is not None else None
        return index if isinstance(index, int) else None

    def show_world(self, has_world: bool) -> None:
        """切换世界身份并清空旧文档和暂存投影。"""
        self._has_world = has_world
        self._busy = False
        self._targets.clear()
        self._tree.clear()
        self._stages.setRowCount(0)
        self._filter.clear()
        self._status.setText(self._t(
            "nbt_editor.scanning" if has_world else "nbt_editor.no_world",
            "正在扫描 NBT 文档..." if has_world else "未加载存档",
        ))
        self._stage_status.setText(self._t(
            "nbt_editor.stage_count", "暂存区: {count} 个变更", count=0
        ))
        self._update_actions()

    def show_targets(self, targets: Sequence[NbtDocumentTarget]) -> None:
        """显示扫描出的文档目标。"""
        self._targets.clear()
        for target in targets:
            self._targets.addItem(target.label, target)
        self._status.setText(self._t(
            "nbt_editor.target_count",
            "发现 {count} 个可编辑文档",
            count=len(targets),
        ))
        self._update_actions()

    def show_loading(self) -> None:
        """显示文档读取中的忙碌状态。"""
        self._status.setText(self._t("nbt_editor.loading", "正在读取文档..."))
        self.set_busy(True)

    def show_document(
        self,
        document: LoadedNbtDocument,
        changes: Sequence[NbtChange],
    ) -> None:
        """投影已加载文档以及该目标的暂存覆盖值。"""
        matching = tuple(
            change for change in changes
            if change.target == document.target.relative_path
        )
        self._tree.load_document(document.data, matching)
        self._status.setText(self._t(
            "nbt_editor.loaded", "已加载: {target}", target=document.target.label
        ))
        self.set_busy(False)

    def show_load_error(self, error: Exception) -> None:
        """恢复可重试状态并显示读取错误摘要。"""
        self._tree.clear()
        self._status.setText(self._t(
            "nbt_editor.load_failed", "读取失败: {error}", error=error
        ))
        self.set_busy(False)

    def show_stages(self, changes: Sequence[NbtChange]) -> None:
        """把完整暂存快照投影到审阅表。"""
        self._stages.setRowCount(len(changes))
        for row, change in enumerate(changes):
            values = (
                change.display_path,
                format_nbt_value(change.old_value, 80),
                format_nbt_value(change.new_value, 80),
                change.format.upper(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(self._INDEX_ROLE, row)
                self._stages.setItem(row, column, item)
        self._stage_status.setText(self._t(
            "nbt_editor.stage_count",
            "暂存区: {count} 个变更",
            count=len(changes),
        ))
        self._update_actions()

    def set_busy(self, busy: bool) -> None:
        """锁定可能改变当前文档或暂存区的控件。"""
        self._busy = busy
        self._update_actions()

    def confirm_discard(self, count: int) -> bool:
        """确认丢弃全部暂存变更。"""
        answer = QMessageBox.question(
            self,
            self._t("nbt_editor.discard_title", "丢弃暂存变更"),
            self._t(
                "nbt_editor.discard_message",
                "确定丢弃全部 {count} 个暂存变更？",
                count=count,
            ),
        )
        return answer == QMessageBox.StandardButton.Yes

    def confirm_commit(self, changes: Sequence[NbtChange]) -> bool:
        """显示带变更摘要的提交确认对话框。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(self._t("nbt_editor.commit_title", "提交 NBT 变更"))
        box.setText(self._t(
            "nbt_editor.commit_message",
            "即将提交 {count} 个变更。提交前会自动备份当前存档。",
            count=len(changes),
        ))
        details = "\n".join(
            f"#{index + 1} {change.target_label}\n"
            f"  {change.display_path}: "
            f"{format_nbt_value(change.old_value)} -> "
            f"{format_nbt_value(change.new_value)}"
            for index, change in enumerate(changes[:80])
        )
        box.setDetailedText(details)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _update_actions(self) -> None:
        has_target = self.selected_target is not None
        has_stages = self._stages.rowCount() > 0
        self._targets.setEnabled(self._has_world and not self._busy)
        self._reload.setEnabled(has_target and not self._busy)
        self._filter.setEnabled(self._has_world and not self._busy)
        self._tree.setEnabled(self._has_world and not self._busy)
        self._remove.setEnabled(
            self.selected_stage_index is not None and not self._busy
        )
        self._discard.setEnabled(has_stages and not self._busy)
        self._commit.setEnabled(has_stages and not self._busy)


__all__ = ["QtNbtPanel"]
