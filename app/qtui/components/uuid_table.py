"""Qt UUID 映射表组件（对应 Flet 树 ``app/ui/components/uuid_table.py``）。

文件读写格式函数复制自 Flet 版（纯逻辑、无 Flet 依赖）；
Flet 树删除后本文件为唯一权威。
"""
from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.qtui.components.buttons import btn_danger, btn_ghost, btn_primary
from app.qtui.theme import get_theme_manager
from core.io_atomic import atomic_write_text

MappingsChange = Callable[[dict[str, str]], None]
PathPicker = Callable[[], Optional[str]]
PathSaver = Callable[[dict[str, str]], Optional[str]]


def read_mappings_file(path: Path) -> dict[str, str]:
    """从文本或 CSV 文件读取映射（不修改控件状态）。

    Args:
        path: 待读取的映射文件。

    Returns:
        Dict[str, str]: 文件中的有效 ``玩家名 -> UUID`` 映射。

    Raises:
        OSError: 文件无法读取。
        UnicodeError: 文件不是有效的 UTF-8 文本。
    """
    if path.suffix.lower() == ".csv":
        return _read_csv_mappings(path)
    return _read_text_mappings(path)


def write_mappings_file(
    path: Path,
    mappings: Mapping[str, str],
) -> int:
    """按稳定顺序原子写入文本映射。

    Args:
        path: 输出文件路径。
        mappings: 待写入的 ``玩家名 -> UUID`` 映射。

    Returns:
        int: 写入的有效映射数量。

    Raises:
        OSError: 文件无法写入或原子替换失败。
    """
    entries = sorted(
        (name.strip(), uuid.strip())
        for name, uuid in mappings.items()
        if name.strip() and uuid.strip()
    )
    if not entries:
        return 0
    content = "".join(f"{name} {uuid}\n" for name, uuid in entries)
    atomic_write_text(path, content, newline="\n")
    return len(entries)


def _read_csv_mappings(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.reader(file):
            if len(row) < 2:
                continue
            name, uuid = row[0].strip(), row[1].strip()
            if name and uuid and not name.startswith("#"):
                loaded[name] = uuid
    return loaded


def _read_text_mappings(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            parts = line.strip().split()
            if len(parts) >= 2 and not line.lstrip().startswith("#"):
                loaded[parts[0]] = parts[1]
    return loaded


class QtUuidMappingTable(QWidget):
    """可编辑的 ``玩家名 -> UUID`` 映射表。"""

    def __init__(
        self,
        mappings: Optional[dict[str, str]] = None,
        *,
        on_mappings_change: Optional[MappingsChange] = None,
        on_import_click: Optional[PathPicker] = None,
        on_export_click: Optional[PathSaver] = None,
    ) -> None:
        """构建映射表。

        Args:
            mappings: 初始映射。
            on_mappings_change: 行内容变化回调。
            on_import_click: 返回导入文件路径（取消返回 None）。
            on_export_click: 接收当前映射并返回导出路径（取消返回 None）。
        """
        super().__init__()
        self._mappings: dict[str, str] = dict(mappings or {})
        self._on_mappings_change = on_mappings_change
        self._on_import_click = on_import_click
        self._on_export_click = on_export_click
        self._rows: list[tuple[QLineEdit, QLineEdit, QWidget]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # 表头
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        name_header = QLabel("玩家名")
        name_header.setStyleSheet("font-weight: 600;")
        uuid_header = QLabel("UUID")
        uuid_header.setStyleSheet("font-weight: 600;")
        header_layout.addWidget(name_header, 2)
        header_layout.addWidget(uuid_header, 3)
        header_layout.addWidget(QLabel(""), 0)
        root.addWidget(header)

        # 行容器
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        root.addWidget(self._rows_container)

        # 工具按钮
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(10)
        toolbar_layout.addWidget(
            btn_primary("＋ 添加一行", on_click=self._add_row)
        )
        toolbar_layout.addWidget(
            btn_ghost("导入名单", on_click=self._import_file)
        )
        toolbar_layout.addWidget(
            btn_ghost("导出名单", on_click=self._export_file)
        )
        toolbar_layout.addWidget(
            btn_danger("清空", on_click=self._clear_all)
        )
        toolbar_layout.addStretch(1)
        root.addWidget(toolbar)

        self._rebuild_rows()

    # ─── 公共接口 ───────────────────────────────

    def set_mappings(self, mappings: Mapping[str, str]) -> None:
        """替换全部映射并重建行。"""
        self._mappings = dict(mappings)
        self._rebuild_rows()

    def get_mappings(self) -> dict[str, str]:
        """返回当前有效映射快照。"""
        return dict(self._mappings)

    def merge_mappings(self, mappings: Mapping[str, str]) -> int:
        """合并已解析映射并同步变更回调。"""
        loaded = dict(mappings)
        if not loaded:
            return 0
        self._mappings.update(loaded)
        self._rebuild_rows()
        self._sync()
        return len(loaded)

    # ─── 行管理 ─────────────────────────────────

    def _rebuild_rows(self) -> None:
        self._clear_rows()
        for name, uuid in sorted(self._mappings.items()):
            self._add_row_with_values(name, uuid)

    def _clear_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

    def _add_row_with_values(self, player_name: str = "", uuid: str = "") -> None:
        theme = get_theme_manager().current
        name_field = QLineEdit(player_name)
        uuid_field = QLineEdit(uuid)
        for field in (name_field, uuid_field):
            field.setStyleSheet(
                f"background-color: {theme.bg_secondary};"
                f"border: 1px solid {theme.border_standard};"
                f"padding: 5px 8px;"
            )
            field.textChanged.connect(lambda _text: self._sync())

        delete_button = QPushButton("🗑️")
        delete_button.setFixedWidth(34)
        delete_button.setToolTip("删除此行")
        delete_button.clicked.connect(
            lambda _checked, nf=name_field, uf=uuid_field: (
                self._delete_row_by_fields(nf, uf)
            )
        )

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        row_layout.addWidget(name_field, 2)
        row_layout.addWidget(uuid_field, 3)
        row_layout.addWidget(delete_button, 0, Qt.AlignmentFlag.AlignTop)
        self._rows_layout.addWidget(row)
        self._rows.append((name_field, uuid_field, row))

    def _add_row(self) -> None:
        self._add_row_with_values()
        self._sync()

    def _delete_row_by_fields(
        self,
        name_field: QLineEdit,
        uuid_field: QLineEdit,
    ) -> None:
        for index, (name, uuid, row_widget) in enumerate(self._rows):
            if name is name_field and uuid is uuid_field:
                self._rows.pop(index)
                self._rows_layout.removeWidget(row_widget)
                row_widget.deleteLater()
                break
        self._sync()

    def _clear_all(self) -> None:
        self._rows.clear()
        self._clear_rows()
        self._mappings.clear()
        if self._on_mappings_change is not None:
            self._on_mappings_change({})

    def _sync(self) -> None:
        new_mappings: dict[str, str] = {}
        for name_field, uuid_field, _row_widget in self._rows:
            name = name_field.text().strip()
            uuid = uuid_field.text().strip()
            if name and uuid:
                new_mappings[name] = uuid
        self._mappings = new_mappings
        if self._on_mappings_change is not None:
            self._on_mappings_change(new_mappings)

    # ─── 导入 / 导出 ────────────────────────────

    def _import_file(self) -> None:
        """触发导入文件操作。"""
        if self._on_import_click is None:
            return
        path = self._on_import_click()
        if not path:
            return
        source = Path(path)
        if not source.exists():
            return
        loaded = read_mappings_file(source)
        self.merge_mappings(loaded)

    def _export_file(self) -> None:
        """触发导出文件操作。"""
        if self._on_export_click is None:
            return
        path = self._on_export_click(self.get_mappings())
        if path:
            write_mappings_file(Path(path), self._mappings)
