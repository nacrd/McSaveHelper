"""Qt NBT 惰性树控件。"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QInputDialog,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from app.models.nbt_edit import NbtChange, NbtPath
from app.presenters.nbt_tree import (
    coerce_nbt_value,
    format_nbt_path,
    format_nbt_value,
    is_nbt_container,
    iter_nbt_children,
    latest_staged_value,
    nbt_type_name,
    raw_nbt_value,
)


Translate = Callable[..., str]
StageChange = Callable[[NbtPath, Any, Any, str], None]


class QtNbtTree(QTreeWidget):
    """按需展开 NBT/JSON 数据，并把叶子编辑转成暂存回调。"""

    MAX_CHILDREN = 300
    _PATH_ROLE = int(Qt.ItemDataRole.UserRole)
    _VALUE_ROLE = _PATH_ROLE + 1
    _LOADED_ROLE = _PATH_ROLE + 2

    def __init__(self, translate: Translate, on_stage: StageChange) -> None:
        """构建树控件。

        Args:
            translate: UI 翻译回调。
            on_stage: 类型转换成功后的暂存命令。
        """
        super().__init__()
        self._translate = translate
        self._on_stage = on_stage
        self._staged_values: tuple[tuple[NbtPath, Any], ...] = ()
        self._values: dict[int, Any] = {}
        self.setColumnCount(3)
        self.setHeaderLabels((
            self._t("nbt_editor.column_name", "名称"),
            self._t("nbt_editor.column_type", "类型"),
            self._t("nbt_editor.column_value", "值"),
        ))
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformRowHeights(True)
        self.header().setStretchLastSection(True)
        self.itemExpanded.connect(self._populate_expanded_item)
        self.itemDoubleClicked.connect(self._edit_item)

    def _t(self, key: str, default: str = "", **kwargs: object) -> str:
        return self._translate(key, default, **kwargs)

    def load_document(
        self,
        data: Any,
        changes: Sequence[NbtChange],
    ) -> None:
        """加载文档根并投影同目标的暂存叶子值。

        Args:
            data: NBT 或 JSON 根节点。
            changes: 当前目标的暂存变更快照。
        """
        self.clear()
        self._values.clear()
        self._staged_values = tuple(
            (change.path, change.new_value) for change in changes
        )
        for key, value in iter_nbt_children(data):
            self._add_item(None, str(key), (key,), value)

    def stage_item_value(self, item: QTreeWidgetItem, raw: str) -> bool:
        """转换叶子输入并发出暂存回调，供对话框与测试复用。

        Args:
            item: 目标树节点。
            raw: 用户输入文本。

        Returns:
            成功暂存时为 True。
        """
        path = item.data(0, self._PATH_ROLE)
        value = self._values.get(id(item))
        if not isinstance(path, tuple) or is_nbt_container(value):
            return False
        try:
            new_value = coerce_nbt_value(raw, value)
        except (TypeError, ValueError) as error:
            QMessageBox.warning(
                self,
                self._t("nbt_editor.invalid_value_title", "值无效"),
                str(error),
            )
            return False
        display_path = format_nbt_path(path)
        self._on_stage(path, value, new_value, display_path)
        self._values[id(item)] = new_value
        item.setText(2, format_nbt_value(new_value))
        return True

    def filter_items(self, query: str) -> None:
        """按已加载节点的名称、类型和值过滤树。

        Args:
            query: 不区分大小写的搜索文本；空文本恢复全部节点。
        """
        normalized = query.strip().casefold()
        for index in range(self.topLevelItemCount()):
            self._filter_item(self.topLevelItem(index), normalized)

    def _filter_item(
        self,
        item: QTreeWidgetItem | None,
        query: str,
    ) -> bool:
        if item is None:
            return False
        child_matches = any(
            self._filter_item(item.child(index), query)
            for index in range(item.childCount())
        )
        own_text = " ".join(item.text(column) for column in range(3)).casefold()
        matched = not query or query in own_text or child_matches
        item.setHidden(not matched)
        return matched

    def _add_item(
        self,
        parent: QTreeWidgetItem | None,
        name: str,
        path: NbtPath,
        disk_value: Any,
    ) -> QTreeWidgetItem:
        value = latest_staged_value(path, self._staged_values, disk_value)
        item = QTreeWidgetItem((
            name,
            nbt_type_name(value),
            format_nbt_value(value),
        ))
        item.setData(0, self._PATH_ROLE, path)
        self._values[id(item)] = value
        item.setData(0, self._LOADED_ROLE, not is_nbt_container(value))
        item.setToolTip(0, format_nbt_path(path))
        item.setToolTip(2, format_nbt_value(value, 1000))
        if parent is None:
            self.addTopLevelItem(item)
        else:
            parent.addChild(item)
        if is_nbt_container(value):
            item.addChild(QTreeWidgetItem(("", "", "")))
        return item

    def _populate_expanded_item(self, item: QTreeWidgetItem) -> None:
        if bool(item.data(0, self._LOADED_ROLE)):
            return
        item.takeChildren()
        value = self._values.get(id(item))
        path = item.data(0, self._PATH_ROLE)
        if not isinstance(path, tuple):
            return
        children = tuple(iter_nbt_children(value))
        for key, child_value in children[:self.MAX_CHILDREN]:
            child_path = path + (key,)
            child_name = f"[{key}]" if isinstance(key, int) else str(key)
            self._add_item(item, child_name, child_path, child_value)
        if len(children) > self.MAX_CHILDREN:
            remaining = len(children) - self.MAX_CHILDREN
            item.addChild(QTreeWidgetItem((
                self._t(
                    "nbt_editor.more_children",
                    "还有 {count} 个子节点未显示",
                    count=remaining,
                ),
                "",
                "",
            )))
        item.setData(0, self._LOADED_ROLE, True)

    def _edit_item(self, item: QTreeWidgetItem, _column: int) -> None:
        value = self._values.get(id(item))
        if is_nbt_container(value) or item.data(0, self._PATH_ROLE) is None:
            return
        text, accepted = QInputDialog.getMultiLineText(
            self,
            self._t("nbt_editor.edit_title", "编辑 NBT 值"),
            format_nbt_path(item.data(0, self._PATH_ROLE)),
            raw_nbt_value(value),
        )
        if accepted:
            self.stage_item_value(item, text)


__all__ = ["QtNbtTree"]
