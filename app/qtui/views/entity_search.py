"""Qt Explorer 实体、方块与容器搜索面板。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.entity_block_search.constants import get_preset_options
from app.services.entity_block_search.models import SearchCondition, SearchResult
from app.qtui.components.cards import placeholder
from app.qtui.utils import batch_widget_updates


Translate = Callable[..., str]
Command = Callable[[], None]


class QtEntitySearchPanel(QWidget):
    """搜索条件、忙碌状态与结果表格。"""

    DISPLAY_LIMIT = 300

    def __init__(
        self,
        translate: Translate,
        on_search: Command,
        on_export: Command,
    ) -> None:
        """构建搜索面板。

        Args:
            translate: UI 翻译回调。
            on_search: 开始搜索命令。
            on_export: 导出结果命令。
        """
        super().__init__()
        self._translate = translate
        self._results: tuple[SearchResult, ...] = ()
        self._has_world = False
        self._build(on_search, on_export)
        self.show_world(False)

    @property
    def results(self) -> tuple[SearchResult, ...]:
        """返回完整搜索结果快照。"""
        return self._results

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def _build(self, on_search: Command, on_export: Command) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_conditions(on_search, on_export))
        status_row = QHBoxLayout()
        self._status = QLabel()
        self._status.setProperty("role", "muted")
        status_row.addWidget(self._status, 1)
        self._count = QLabel()
        self._count.setProperty("role", "muted")
        status_row.addWidget(self._count)
        layout.addLayout(status_row)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)
        # 状态：条件栏保持稳定，内容区只显示当前可操作或可阅读的状态。
        self._content_stack = QStackedWidget()
        self._no_world_state = placeholder(
            "🔎",
            self._t("entity_search.no_world", "未加载存档"),
            self._t(
                "workspace.select_world_hint",
                "选择包含 level.dat 的 Minecraft Java 世界目录",
            ),
            expand=True,
        )
        self._ready_state = placeholder(
            "⌕",
            self._t("entity_search.ready", "未开始搜索"),
            self._t(
                "entity_search.ready_hint",
                "设置目标、维度和搜索范围后开始搜索。",
            ),
            expand=True,
        )
        self._no_results_state = placeholder(
            "∅",
            self._t("entity_search.no_results", "没有搜索结果"),
            self._t(
                "entity_search.no_results_hint",
                "调整目标 ID、预设或维度范围后重试。",
            ),
            expand=True,
        )
        self._table = self._build_result_table()
        self._content_stack.addWidget(self._no_world_state)
        self._content_stack.addWidget(self._ready_state)
        self._content_stack.addWidget(self._no_results_state)
        self._content_stack.addWidget(self._table)
        layout.addWidget(self._content_stack, 1)

    def _build_conditions(
        self,
        on_search: Command,
        on_export: Command,
    ) -> QWidget:
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel(self._t(
            "entity_search.scope", "搜索范围"
        )), 0, 0)
        self._type = QComboBox()
        self._type.addItem(self._t("entity_search.entity", "实体"), "entity")
        self._type.addItem(self._t("entity_search.block", "方块"), "block")
        self._type.addItem(
            self._t("entity_search.container", "容器"), "container"
        )
        self._type.currentIndexChanged.connect(self._update_presets)
        grid.addWidget(self._type, 0, 1)
        grid.addWidget(QLabel(self._t(
            "entity_search.target", "目标 ID"
        )), 0, 2)
        self._target = QLineEdit()
        self._target.setPlaceholderText(self._t(
            "entity_search.target_hint", "例如 minecraft:villager 或 *shulker*"
        ))
        self._target.returnPressed.connect(on_search)
        grid.addWidget(self._target, 0, 3)
        grid.addWidget(QLabel(self._t(
            "entity_search.preset", "常用预设"
        )), 0, 4)
        self._preset = QComboBox()
        self._preset.activated.connect(self._apply_preset)
        grid.addWidget(self._preset, 0, 5)

        grid.addWidget(QLabel(self._t(
            "entity_search.dimensions", "维度"
        )), 1, 0)
        dimensions = QWidget()
        dimension_layout = QHBoxLayout(dimensions)
        dimension_layout.setContentsMargins(0, 0, 0, 0)
        self._overworld = QCheckBox(self._t(
            "entity_search.overworld", "主世界"
        ))
        self._nether = QCheckBox(self._t("entity_search.nether", "下界"))
        self._end = QCheckBox(self._t("entity_search.end", "末地"))
        for box in (self._overworld, self._nether, self._end):
            box.setChecked(True)
            dimension_layout.addWidget(box)
        dimension_layout.addStretch(1)
        grid.addWidget(dimensions, 1, 1, 1, 3)
        self._search = QPushButton(
            f"🔍  {self._t('entity_search.start', '开始搜索')}"
        )
        self._search.setProperty("role", "primary")
        self._search.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search.clicked.connect(lambda _checked: on_search())
        grid.addWidget(self._search, 1, 4)
        self._export = QPushButton(
            f"📤  {self._t('entity_search.export', '导出结果')}"
        )
        self._export.setProperty("role", "ghost")
        self._export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export.clicked.connect(lambda _checked: on_export())
        grid.addWidget(self._export, 1, 5)
        grid.setColumnStretch(3, 1)
        self._update_presets()
        return host

    def _build_result_table(self) -> QTableWidget:
        headers = (
            "#",
            self._t("entity_search.column_target", "目标"),
            self._t("entity_search.column_type", "类型"),
            self._t("entity_search.column_dimension", "维度"),
            "X",
            "Y",
            "Z",
            self._t("entity_search.column_details", "详情"),
        )
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        return table

    def condition(self, world_path: Path) -> SearchCondition:
        """从当前控件值构造搜索条件。"""
        dimensions: list[str] = []
        if self._overworld.isChecked():
            dimensions.append("overworld")
        if self._nether.isChecked():
            dimensions.append("nether")
        if self._end.isChecked():
            dimensions.append("end")
        return SearchCondition(
            search_type=str(self._type.currentData()),
            target=self._target.text().strip(),
            dimensions=dimensions,
            world_path=world_path,
        )

    def show_world(self, has_world: bool) -> None:
        """切换世界并清除旧世界结果。"""
        self._has_world = has_world
        self._results = ()
        self._table.setRowCount(0)
        self._count.clear()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._status.setText(self._t(
            "entity_search.ready" if has_world else "entity_search.no_world",
            "未开始搜索" if has_world else "未加载存档",
        ))
        self._content_stack.setCurrentWidget(
            self._ready_state if has_world else self._no_world_state
        )
        self._set_busy(False)

    def show_search_started(self) -> None:
        """显示搜索忙碌状态。"""
        self._status.setText(self._t(
            "entity_search.searching", "正在搜索..."
        ))
        self._count.clear()
        self._progress.setRange(0, 0)
        self._content_stack.setCurrentWidget(
            self._table if self._results else self._ready_state
        )
        self._set_busy(True)

    def show_search_success(self, results: Sequence[SearchResult]) -> None:
        """投影搜索结果并保留完整结果快照。"""
        self._results = tuple(results)
        displayed = self._results[:self.DISPLAY_LIMIT]
        with batch_widget_updates(self._table):
            self._table.setRowCount(len(displayed))
            for row, result in enumerate(displayed):
                details = json.dumps(
                    result.extra_info,
                    ensure_ascii=False,
                    sort_keys=True,
                ) if result.extra_info else ""
                values = (
                    row + 1,
                    result.target_id,
                    self._type_label(result.result_type),
                    self._dimension_label(result.dimension),
                    result.x,
                    result.y,
                    result.z,
                    details,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    self._table.setItem(row, column, item)
        self._status.setText(self._t(
            "entity_search.done", "搜索完成"
        ))
        if len(self._results) > len(displayed):
            count = self._t(
                "entity_search.count_limited",
                "显示前 {displayed} 个，共 {total} 个",
                displayed=len(displayed),
                total=len(self._results),
            )
        else:
            count = self._t(
                "entity_search.count",
                "{total} 个结果",
                total=len(self._results),
            )
        self._count.setText(count)
        self._content_stack.setCurrentWidget(
            self._table if self._results else self._no_results_state
        )
        self._finish_busy()

    def show_search_failure(self, error: Exception) -> None:
        """显示搜索失败状态。"""
        self._status.setText(self._t(
            "entity_search.failed", "搜索失败"
        ))
        self._count.setText(str(error))
        self._content_stack.setCurrentWidget(
            self._table if self._results else self._ready_state
        )
        self._finish_busy()

    def show_search_cancelled(self) -> None:
        """显示搜索取消状态。"""
        self._status.setText(self._t(
            "entity_search.cancelled", "搜索已取消"
        ))
        self._content_stack.setCurrentWidget(
            self._table if self._results else self._ready_state
        )
        self._finish_busy()

    def show_export_started(self) -> None:
        """锁定搜索与导出命令。"""
        self._status.setText(self._t(
            "entity_search.exporting", "正在导出..."
        ))
        self._progress.setRange(0, 0)
        self._set_busy(True)

    def show_export_finished(self) -> None:
        """恢复搜索与导出命令。"""
        self._status.setText(self._t(
            "entity_search.done", "搜索完成"
        ))
        self._finish_busy()

    def _finish_busy(self) -> None:
        self._progress.setRange(0, 100)
        self._progress.setValue(100 if self._results else 0)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._search.setEnabled(self._has_world and not busy)
        self._export.setEnabled(bool(self._results) and not busy)
        self._type.setEnabled(not busy)
        self._target.setEnabled(not busy)
        self._preset.setEnabled(not busy)
        for box in (self._overworld, self._nether, self._end):
            box.setEnabled(not busy)

    def _update_presets(self, _index: int = 0) -> None:
        current = self._preset.currentData() if hasattr(self, "_preset") else None
        self._preset.clear()
        self._preset.addItem(self._t("entity_search.choose_preset", "选择预设"), "")
        for preset_id, _label in get_preset_options(
            str(self._type.currentData())
        ):
            self._preset.addItem(preset_id, preset_id)
        if current:
            index = self._preset.findData(current)
            if index >= 0:
                self._preset.setCurrentIndex(index)

    def _apply_preset(self, _index: int) -> None:
        value = self._preset.currentData()
        if value:
            self._target.setText(str(value))

    def _type_label(self, search_type: str) -> str:
        labels = {
            "entity": self._t("entity_search.entity", "实体"),
            "block": self._t("entity_search.block", "方块"),
            "container": self._t("entity_search.container", "容器"),
        }
        return labels.get(search_type, search_type)

    def _dimension_label(self, dimension: str) -> str:
        labels = {
            "overworld": self._t("entity_search.overworld", "主世界"),
            "nether": self._t("entity_search.nether", "下界"),
            "end": self._t("entity_search.end", "末地"),
        }
        return labels.get(dimension, dimension)


__all__ = ["QtEntitySearchPanel"]
