"""Qt 侧边栏：品牌、当前存档、标签导航、最近存档。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.qtui.icons import glyph

Translate = Callable[..., str]


class _TabButton(QPushButton):
    """侧边栏标签按钮（可选中、可折叠为图标）。"""

    def __init__(
        self,
        view_id: str,
        icon: str,
        label: str,
        on_click: Callable[[str], None],
    ) -> None:
        super().__init__(f"{icon}  {label}")
        self._view_id = view_id
        self._icon = icon
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setToolTip(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda _checked: on_click(view_id))

    def set_collapsed(self, collapsed: bool) -> None:
        """折叠时仅显示图标。"""
        self.setText(self._icon if collapsed else f"{self._icon}  {self.text().split('  ', 1)[-1]}")


class QtSidebar(QFrame):
    """左侧导航栏：支持折叠为图标窄栏。"""

    EXPANDED_WIDTH = 220
    COLLAPSED_WIDTH = 56

    def __init__(
        self,
        tabs: list[dict[str, str]],
        *,
        translate: Translate,
        on_tab_select: Callable[[str], None],
        on_import_save: Optional[Callable[[], None]] = None,
        on_recent_save_select: Optional[Callable[[str], None]] = None,
        recent_saves: Optional[list[dict[str, Any]]] = None,
        current_save_path: Optional[str] = None,
        on_pick_current_save: Optional[Callable[[], None]] = None,
    ) -> None:
        """构建 Qt 侧边栏。

        Args:
            tabs: 侧边栏条目（``id``/``label``/``icon``）。
            translate: 翻译函数。
            on_tab_select: 标签选中回调（view_id）。
            on_import_save: 导入存档回调。
            on_recent_save_select: 最近存档选中回调（路径）。
            recent_saves: 最近存档列表。
            current_save_path: 当前存档路径。
            on_pick_current_save: 选择当前存档回调。
        """
        super().__init__()
        self._translate = translate
        self._on_tab_select = on_tab_select
        self._on_recent_save_select = on_recent_save_select
        self._recent_saves: list[dict[str, Any]] = list(recent_saves or [])
        self._collapsed = False
        self._tabs: list[dict[str, str]] = list(tabs)
        self._buttons: dict[str, _TabButton] = {}

        self.setFixedWidth(self.EXPANDED_WIDTH)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(8, 10, 8, 10)
        self._root.setSpacing(6)

        # 品牌 + 折叠开关
        self._brand_row = QHBoxLayout()
        self._brand_label = QLabel("⛏️ MCSaveHelper")
        self._brand_label.setStyleSheet(
            "font-size: 15px; font-weight: 700; "
            "letter-spacing: 0.5px; color: #F2F5F3;"
        )
        self._toggle_button = QPushButton("◀")
        self._toggle_button.setFixedWidth(24)
        self._toggle_button.setToolTip(translate("sidebar.collapse", "折叠"))
        self._toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_button.clicked.connect(lambda: self.toggle_collapsed())
        self._brand_row.addWidget(self._brand_label)
        self._brand_row.addStretch(1)
        self._brand_row.addWidget(self._toggle_button)
        self._root.addLayout(self._brand_row)

        # 当前存档
        self._save_label = QLabel(
            translate("sidebar.no_current_save", "未设置当前存档")
        )
        self._save_label.setProperty("role", "muted")
        self._save_label.setWordWrap(True)
        self._save_label.setToolTip(current_save_path or "")
        self._root.addWidget(self._save_label)
        self._set_current_button = QPushButton(
            translate("sidebar.set_current_save", "选择存档")
        )
        self._set_current_button.setProperty("role", "ghost")
        self._set_current_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_current_button.clicked.connect(
            lambda: self._call(on_pick_current_save)
        )
        self._root.addWidget(self._set_current_button)

        # 标签列表
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        tabs_container = QWidget()
        self._tabs_layout = QVBoxLayout(tabs_container)
        self._tabs_layout.setContentsMargins(0, 0, 0, 0)
        self._tabs_layout.setSpacing(4)
        for tab in self._tabs:
            self._add_tab_button(tab)
        self._tabs_layout.addStretch(1)
        scroll.setWidget(tabs_container)
        self._root.addWidget(scroll, 1)

        # 最近存档
        self._recent_header = QLabel(
            translate("sidebar.recent_saves", "最近存档")
        )
        self._recent_header.setProperty("role", "muted")
        self._recent_header.setVisible(bool(self._recent_saves))
        self._root.addWidget(self._recent_header)
        self._recent_layout = QVBoxLayout()
        self._recent_layout.setSpacing(2)
        self._rebuild_recent_saves()
        self._root.addLayout(self._recent_layout)

        # 导入存档
        self._import_button = QPushButton(
            f"{glyph('PLUS')}  {translate('sidebar.import_save', '导入存档')}"
        )
        self._import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._import_button.clicked.connect(lambda: self._call(on_import_save))
        self._root.addWidget(self._import_button)

    # ─── 公共操作 ───────────────────────────────

    def select_tab(self, view_id: str) -> None:
        """选中指定标签。"""
        button = self._buttons.get(view_id)
        if button is not None:
            button.setChecked(True)

    def set_current_save(self, path: Optional[str]) -> None:
        """更新当前存档显示。"""
        self._save_label.setText(path or self._translate(
            "sidebar.no_current_save", "未设置当前存档"
        ))
        self._save_label.setToolTip(path or "")
        self._save_label.setVisible(not self._collapsed)

    def set_recent_saves(self, saves: list[dict[str, Any]]) -> None:
        """更新最近存档列表。"""
        self._recent_saves = list(saves)
        self._recent_header.setVisible(
            bool(self._recent_saves) and not self._collapsed
        )
        self._rebuild_recent_saves()

    def toggle_collapsed(self) -> None:
        """切换折叠状态。"""
        self._set_collapsed(not self._collapsed)

    def _set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        width = self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH
        self.setFixedWidth(width)
        self._brand_label.setVisible(not collapsed)
        self._save_label.setVisible(not collapsed)
        self._set_current_button.setVisible(not collapsed)
        self._recent_header.setVisible(
            not collapsed and bool(self._recent_saves)
        )
        self._import_button.setText(
            glyph("PLUS") if collapsed else (
                f"{glyph('PLUS')}  {self._translate('sidebar.import_save', '导入存档')}"
            )
        )
        for button in self._buttons.values():
            button.set_collapsed(collapsed)
        self._toggle_button.setText("▶" if collapsed else "◀")
        self._toggle_button.setToolTip(
            self._translate("sidebar.expand", "展开")
            if collapsed
            else self._translate("sidebar.collapse", "折叠")
        )

    # ─── 内部构建 ───────────────────────────────

    def _add_tab_button(self, tab: dict[str, str]) -> None:
        view_id = tab["id"]
        button = _TabButton(
            view_id=view_id,
            icon=tab["icon"],
            label=tab["label"],
            on_click=self._on_tab_select,
        )
        self._buttons[view_id] = button
        self._tabs_layout.addWidget(button)

    def _rebuild_recent_saves(self) -> None:
        """重建最近存档按钮列表（幂等）。"""
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for save in self._recent_saves:
            path = str(save.get("path", ""))
            name = str(save.get("name") or path)
            button = QPushButton(name)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(path)
            button.setStyleSheet("text-align: left; padding: 3px 8px;")
            callback = self._on_recent_save_select
            if callback is not None:
                self._connect_recent_save(button, callback, path)
            self._recent_layout.addWidget(button)

    @staticmethod
    def _connect_recent_save(
        button: QPushButton,
        callback: Callable[[str], None],
        path: str,
    ) -> None:
        """把最近存档按钮连接到回调（避免闭包窄化问题）。"""

        def on_clicked(_checked: bool) -> None:
            callback(path)

        button.clicked.connect(on_clicked)

    @staticmethod
    def _call(callback: Optional[Callable[[], None]]) -> None:
        if callback is not None:
            callback()
