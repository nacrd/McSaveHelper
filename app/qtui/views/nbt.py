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

from app.models.nbt_edit import ChunkNbtTarget, NbtChange, NbtPath
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
        on_load_chunk: Command,
        on_fill_world_coords: Command,
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
            on_load_chunk: 按区域路径加载区块 NBT。
            on_fill_world_coords: 用世界坐标填充区域/区块字段。
        """
        super().__init__()
        self._translate = translate
        self._has_world = False
        self._busy = False
        self._build(
            on_load,
            on_reload,
            on_stage,
            on_remove,
            on_discard,
            on_commit,
            on_load_chunk,
            on_fill_world_coords,
        )
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
        on_load_chunk: Command,
        on_fill_world_coords: Command,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._tree = QtNbtTree(self._translate, on_stage)
        layout.addLayout(self._build_toolbar(on_load, on_reload))
        layout.addLayout(
            self._build_chunk_row(on_load_chunk, on_fill_world_coords)
        )
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

    def _build_chunk_row(
        self,
        on_load_chunk: Command,
        on_fill_world_coords: Command,
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel(self._t("nbt_editor.region_file", "区域")))
        self._region_file = QLineEdit()
        self._region_file.setPlaceholderText("region/r.0.0.mca")
        row.addWidget(self._region_file, 2)
        row.addWidget(QLabel(self._t("nbt_editor.chunk_x", "区块 X")))
        self._chunk_x = QLineEdit("0")
        self._chunk_x.setFixedWidth(56)
        row.addWidget(self._chunk_x)
        row.addWidget(QLabel(self._t("nbt_editor.chunk_z", "区块 Z")))
        self._chunk_z = QLineEdit("0")
        self._chunk_z.setFixedWidth(56)
        row.addWidget(self._chunk_z)
        row.addWidget(QLabel(self._t("nbt_editor.world_x", "世界 X")))
        self._world_x = QLineEdit("0")
        self._world_x.setFixedWidth(72)
        row.addWidget(self._world_x)
        row.addWidget(QLabel(self._t("nbt_editor.world_z", "世界 Z")))
        self._world_z = QLineEdit("0")
        self._world_z.setFixedWidth(72)
        row.addWidget(self._world_z)
        self._fill_coords = QPushButton(self._t(
            "nbt_editor.fill_coords", "填入坐标"
        ))
        self._fill_coords.clicked.connect(
            lambda _checked: on_fill_world_coords()
        )
        row.addWidget(self._fill_coords)
        self._load_chunk = QPushButton(self._t(
            "nbt_editor.load_chunk", "加载区块"
        ))
        self._load_chunk.setProperty("role", "primary")
        self._load_chunk.clicked.connect(lambda _checked: on_load_chunk())
        row.addWidget(self._load_chunk)
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
        self._region_file.clear()
        self._chunk_x.setText("0")
        self._chunk_z.setText("0")
        self._world_x.setText("0")
        self._world_z.setText("0")
        self._status.setText(self._t(
            "nbt_editor.scanning" if has_world else "nbt_editor.no_world",
            "正在扫描 NBT 文档..." if has_world else "未加载存档",
        ))
        self._stage_status.setText(self._t(
            "nbt_editor.stage_count", "暂存区: {count} 个变更", count=0
        ))
        self._update_actions()

    @property
    def region_file_text(self) -> str:
        """返回区域文件相对路径输入。"""
        return self._region_file.text().strip().replace("\\", "/")

    @property
    def chunk_coords(self) -> tuple[int, int]:
        """返回区块局部坐标；非法时抛出 ValueError。"""
        return int(self._chunk_x.text().strip()), int(self._chunk_z.text().strip())

    @property
    def world_coords(self) -> tuple[float, float]:
        """返回世界 X/Z 输入；非法时抛出 ValueError。"""
        return float(self._world_x.text().strip()), float(self._world_z.text().strip())

    def set_chunk_fields(
        self,
        region_file: str,
        chunk_x: int,
        chunk_z: int,
        *,
        world_x: int | None = None,
        world_z: int | None = None,
    ) -> None:
        """写入区块加载表单字段。"""
        self._region_file.setText(region_file)
        self._chunk_x.setText(str(chunk_x))
        self._chunk_z.setText(str(chunk_z))
        if world_x is not None:
            self._world_x.setText(str(world_x))
        if world_z is not None:
            self._world_z.setText(str(world_z))

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

    def show_chunk(
        self,
        target: ChunkNbtTarget,
        label: str,
        changes: Sequence[NbtChange],
    ) -> None:
        """投影已加载区块以及该区块目标的暂存覆盖值。"""
        matching = tuple(
            change for change in changes
            if isinstance(change.target, ChunkNbtTarget)
            and change.target.key == target.key
        )
        self._tree.load_document(target.data, matching)
        self._status.setText(self._t(
            "nbt_editor.loaded", "已加载: {target}", target=label
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
        enabled = self._has_world and not self._busy
        self._targets.setEnabled(enabled)
        self._reload.setEnabled(has_target and not self._busy)
        self._filter.setEnabled(enabled)
        self._tree.setEnabled(enabled)
        self._region_file.setEnabled(enabled)
        self._chunk_x.setEnabled(enabled)
        self._chunk_z.setEnabled(enabled)
        self._world_x.setEnabled(enabled)
        self._world_z.setEnabled(enabled)
        self._fill_coords.setEnabled(enabled)
        self._load_chunk.setEnabled(enabled)
        self._remove.setEnabled(
            self.selected_stage_index is not None and not self._busy
        )
        self._discard.setEnabled(has_stages and not self._busy)
        self._commit.setEnabled(has_stages and not self._busy)


__all__ = ["QtNbtPanel"]
