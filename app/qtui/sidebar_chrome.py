"""Qt 侧边栏头部/页脚/切换构建器（与 Flet 版 sidebar_chrome.py 布局一致）。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.qtui.icons import glyph
from app.qtui.theme import QtThemeColors, get_theme_manager
from core.version import APP_VERSION


def _colors() -> QtThemeColors:
    return get_theme_manager().current


def build_brand_box() -> QWidget:
    """品牌方块：accent 背景 + 镐图标。"""
    box = QLabel(glyph("PICKAXE"))
    box.setFixedSize(38, 38)
    box.setAlignment(Qt.AlignmentFlag.AlignCenter)
    colors = _colors()
    box.setStyleSheet(
        f"background-color: {colors.accent}; color: {colors.text_invert};"
        " border-radius: 6px; font-size: 20px;"
    )
    return box


def build_brand_block() -> QWidget:
    """品牌行：accent 方块 + 标题 + 副标题。"""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(build_brand_box())
    text_col = QWidget()
    text_layout = QVBoxLayout(text_col)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)
    colors = _colors()
    title = QLabel("MCSaveHelper")
    title.setStyleSheet(
        f"color: {colors.text_primary}; font-size: 15px; font-weight: 600;"
    )
    subtitle = QLabel("Minecraft Save Toolkit")
    subtitle.setStyleSheet(
        f"color: {colors.text_secondary}; font-size: 11px;"
    )
    text_layout.addWidget(title)
    text_layout.addWidget(subtitle)
    layout.addWidget(text_col, 1)
    return row


def build_current_save_block(
    current_save_name: str,
    label: str,
) -> QWidget:
    """当前存档块：bg_primary 卡片 + 保存图标 + 标签 + 名称。"""
    colors = _colors()
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background-color: {colors.bg_primary};"
        f" border: 1px solid {colors.border_subtle}; border-radius: 6px; }}"
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(5)
    label_row = QHBoxLayout()
    label_row.setContentsMargins(0, 0, 0, 0)
    label_row.setSpacing(6)
    icon = QLabel(glyph("SAVE"))
    icon.setStyleSheet(f"color: {colors.mc_grass}; font-size: 14px;")
    label_widget = QLabel(label)
    label_widget.setStyleSheet(
        f"color: {colors.text_secondary}; font-size: 12px; font-weight: 600;"
        " font-family: monospace;"
    )
    label_row.addWidget(icon)
    label_row.addWidget(label_widget)
    label_row.addStretch(1)
    layout.addLayout(label_row)
    name = QLabel(current_save_name)
    is_set = current_save_name != "未设置当前存档"
    name_color = colors.mc_gold if is_set else colors.text_secondary
    name.setStyleSheet(
        f"color: {name_color}; font-size: 13px; font-weight: 600;"
    )
    name.setWordWrap(True)
    layout.addWidget(name)
    return card


def build_set_current_save_button(
    on_set_current_save: Callable[[], None],
    label: str,
) -> QWidget:
    """设置当前存档按钮：accent 背景 + 文件夹图标。"""
    button = QPushButton(f"{glyph('FOLDER_OPEN')}  {label}")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    colors = _colors()
    button.setStyleSheet(
        f"QPushButton {{ background-color: {colors.accent}; color:"
        f" {colors.text_invert}; border: none; border-radius: 6px;"
        " font-size: 12px; font-weight: 600; padding: 10px 12px;"
        " text-align: center; }"
        f" QPushButton:hover {{ background-color: {colors.accent_hover}; }}"
        f" QPushButton:pressed {{ background-color: {colors.accent_dim}; }}"
    )
    button.clicked.connect(lambda: on_set_current_save())
    return button


class _RecentHeader(QWidget):
    """最近存档标题行（可点击切换展开/收起）。"""

    def __init__(
        self,
        label: str,
        arrow_state: bool,
        on_toggle: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_toggle = on_toggle
        colors = _colors()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        icon = QLabel(glyph("CLOCK"))
        icon.setStyleSheet(f"color: {colors.text_secondary}; font-size: 16px;")
        label_widget = QLabel(label)
        label_widget.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 12px; font-weight: 600;"
        )
        self._arrow = QLabel(glyph("CHEVRON_RIGHT"))
        self.set_arrow_state(arrow_state)
        layout.addWidget(icon)
        layout.addWidget(label_widget)
        layout.addStretch(1)
        layout.addWidget(self._arrow)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_arrow_state(self, expanded: bool) -> None:
        colors = _colors()
        self._arrow.setText(
            glyph("CHEVRON_DOWN" if expanded else "CHEVRON_RIGHT")
        )
        self._arrow.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 14px;"
        )

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_toggle()
        super().mouseReleaseEvent(event)


def build_recent_header(
    label: str,
    arrow_state: bool,
    on_toggle_recent: Callable[[], None],
) -> QWidget:
    """最近存档标题行：时钟图标 + 标签 + chevron。"""
    return _RecentHeader(label, arrow_state, on_toggle_recent)


def build_header_expanded(
    *,
    current_save_name: str,
    current_save_label: str,
    set_current_label: str,
    recent_saves_label: str,
    recent_arrow_state: bool,
    on_set_current_save: Callable[[], None],
    on_toggle_recent: Callable[[], None],
) -> QWidget:
    """展开侧边栏头部：品牌、当前存档、设置按钮、最近存档标题。"""
    colors = _colors()
    container = QWidget()
    container.setStyleSheet(
        f"QWidget {{ background-color: {colors.bg_secondary}; }}"
    )
    layout = QVBoxLayout(container)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(0)
    layout.addWidget(build_brand_block())
    spacer = QWidget()
    spacer.setFixedHeight(16)
    layout.addWidget(spacer)
    layout.addWidget(build_current_save_block(current_save_name, current_save_label))
    set_button = build_set_current_save_button(on_set_current_save, set_current_label)
    margin_widget = QWidget()
    ml = QVBoxLayout(margin_widget)
    ml.setContentsMargins(0, 10, 0, 0)
    ml.addWidget(set_button)
    layout.addWidget(margin_widget)
    recent_wrap = QWidget()
    rw = QVBoxLayout(recent_wrap)
    rw.setContentsMargins(0, 14, 0, 0)
    rw.addWidget(build_recent_header(
        recent_saves_label, recent_arrow_state, on_toggle_recent
    ))
    layout.addWidget(recent_wrap)
    return container


def build_header_collapsed(
    on_set_current_save: Callable[[], None],
    set_current_tooltip: str,
    recent_menu: Optional[QWidget] = None,
) -> QWidget:
    """折叠侧边栏头部：品牌方块 + 设置存档方块。"""
    colors = _colors()
    container = QWidget()
    container.setStyleSheet(
        f"QWidget {{ background-color: {colors.bg_secondary};"
        f" border-bottom: 1px solid {colors.border_subtle}; }}"
    )
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 8, 0, 8)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    brand = QLabel(glyph("PICKAXE"))
    brand.setFixedSize(44, 44)
    brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
    brand.setStyleSheet(
        f"color: {colors.accent}; font-size: 22px;"
    )
    layout.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
    set_btn = QPushButton(glyph("FOLDER_OPEN"))
    set_btn.setFixedSize(44, 44)
    set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    set_btn.setToolTip(set_current_tooltip)
    set_btn.setStyleSheet(
        f"QPushButton {{ background-color: {colors.accent}; color:"
        f" {colors.text_invert}; border: none; border-radius: 6px;"
        " font-size: 20px; }"
        f" QPushButton:hover {{ background-color: {colors.accent_hover}; }}"
    )
    set_btn.clicked.connect(lambda: on_set_current_save())
    layout.addWidget(set_btn, 0, Qt.AlignmentFlag.AlignHCenter)
    if recent_menu is not None:
        layout.addWidget(recent_menu, 0, Qt.AlignmentFlag.AlignHCenter)
    return container


class _ToggleButton(QPushButton):
    """带折叠态切换的按钮（供 sidebar 在折叠后更新图标）。"""

    def set_collapsed(self, collapsed: bool) -> None:
        self.setText(glyph("ARROW_RIGHT" if collapsed else "ARROW_LEFT"))


def build_toggle_button(
    *,
    collapsed: bool,
    on_toggle: Callable[[], None],
    tooltip: str | None = None,
) -> _ToggleButton:
    """侧边栏折叠/展开切换按钮（顶部边框分隔）。"""
    colors = _colors()
    button = _ToggleButton(
        glyph("ARROW_RIGHT" if collapsed else "ARROW_LEFT")
    )
    button.setFixedSize(44, 44)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(tooltip or ("展开侧边栏" if collapsed else "收起侧边栏"))
    button.setStyleSheet(
        f"QPushButton {{ background-color: {colors.bg_secondary}; color:"
        f" {colors.text_secondary}; border: none;"
        f" border-top: 1px solid {colors.border_subtle}; font-size: 16px; }}"
        f" QPushButton:hover {{ color: {colors.text_primary};"
        f" background-color: {colors.bg_card_hover}; }}"
    )
    button.clicked.connect(lambda: on_toggle())
    return button


class _Footer(QWidget):
    """侧边栏页脚版本信息；折叠态返回零高度占位。"""

    def __init__(self, collapsed: bool) -> None:
        super().__init__()
        self._collapsed = collapsed
        self._rebuild()

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._rebuild()

    def _rebuild(self) -> None:
        layout = self.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.deleteLater()
            layout.deleteLater()
        colors = _colors()
        if self._collapsed:
            self.setFixedHeight(0)
            return
        self.setMinimumHeight(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        version = QLabel(APP_VERSION)
        version.setStyleSheet(
            f"color: {colors.text_secondary}; font-size: 10px;"
        )
        tag = QLabel("▣ stone edition")
        tag.setStyleSheet(f"color: {colors.text_muted}; font-size: 10px;")
        layout.addWidget(version)
        layout.addStretch(1)
        layout.addWidget(tag)


def build_footer(collapsed: bool) -> _Footer:
    """侧边栏页脚版本信息；折叠态返回零高度占位。"""
    return _Footer(collapsed)


__all__ = [
    "build_brand_block",
    "build_brand_box",
    "build_current_save_block",
    "build_footer",
    "build_header_collapsed",
    "build_header_expanded",
    "build_recent_header",
    "build_set_current_save_button",
    "build_toggle_button",
]
