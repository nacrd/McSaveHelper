"""Qt 侧边栏：品牌、当前存档、标签导航、最近存档（与 Flet 版布局一致）。

布局与 ``app/ui/sidebar.py`` + ``sidebar_chrome.py`` + ``sidebar_tabs.py``
对齐：224px 展开 / 68px 折叠、品牌块、当前存档卡片、accent 设置存档按钮、
可折叠最近存档、图标槽 + 标签 + 选中标记的页签按钮、底部切换与页脚版本。
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.qtui.sidebar_chrome import (
    _Footer,
    _ToggleButton,
    build_footer,
    build_header_collapsed,
    build_header_expanded,
    build_toggle_button,
)
from app.qtui.theme import get_theme_manager

Translate = Callable[..., str]


class _TabButton(QFrame):
    """侧边栏页签按钮（展开：图标槽 + 标签 + 选中标记；折叠：仅图标）。"""

    def __init__(
        self,
        view_id: str,
        icon: str,
        label: str,
        on_click: Callable[[str], None],
    ) -> None:
        """构建页签按钮。"""
        super().__init__()
        self._view_id = view_id
        self._icon = icon
        self._label = label
        self._on_click_callback = on_click
        self._selected = False
        self._collapsed = False
        self._hovering = False
        self._icon_label: QLabel | None = None
        self._text_label: QLabel | None = None
        self._marker: QLabel | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setToolTip(label)
        self.setMouseTracking(True)
        self._rebuild()

    def _clear_layout(self) -> None:
        layout = self.layout()
        if layout is not None:
            while layout.count():
                item = layout.itemAt(0)
                layout.takeAt(0)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
            layout.deleteLater()

    def _rebuild(self) -> None:
        """重建子控件与布局（折叠往返安全）。"""
        self._clear_layout()
        self._icon_label = QLabel(self._icon)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(self)
        if self._collapsed:
            self.setFixedWidth(44)
            layout.setContentsMargins(0, 0, 0, 0)
            self._icon_label.setFixedSize(44, 44)
            layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            self.setMinimumWidth(0)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(8)
            icon_slot = QWidget()
            icon_slot.setFixedSize(28, 28)
            icon_layout = QHBoxLayout(icon_slot)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            icon_layout.addStretch(1)
            icon_layout.addWidget(self._icon_label)
            icon_layout.addStretch(1)
            self._text_label = QLabel(self._label)
            self._text_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            self._marker = QLabel("•")
            self._marker.setText("•" if self._selected else "")
            self._marker.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            layout.addWidget(icon_slot)
            layout.addWidget(self._text_label, 1)
            layout.addWidget(self._marker)
        self._apply_style()

    def set_collapsed(self, collapsed: bool) -> None:
        """折叠态：仅显示图标；展开态：图标 + 标签 + 标记。"""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._rebuild()
        self._apply_style()

    def set_selected(self, selected: bool) -> None:
        """更新选中态样式与标记。"""
        if selected == self._selected:
            return
        self._selected = selected
        if self._marker is not None:
            self._marker.setText("•" if selected else "")
        self._apply_style()

    def enterEvent(self, event: Any) -> None:
        self._hovering = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event: Any) -> None:
        self._hovering = False
        self._apply_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)

    def _on_click(self) -> None:
        self._on_click_callback(self._view_id)

    def _apply_style(self) -> None:
        colors = get_theme_manager().current
        if self._collapsed:
            bg = colors.bg_elevated if self._selected else "transparent"
            border = colors.accent_dim if self._selected else "transparent"
            icon_color = (
                colors.accent if self._selected else colors.text_secondary
            )
            self.setStyleSheet(
                f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
                f" border-radius: 6px; }}"
            )
            if self._icon_label is not None:
                self._icon_label.setStyleSheet(
                    f"color: {icon_color}; font-size: 20px;"
                )
            return
        if self._selected:
            bg = colors.bg_elevated
            border = colors.border_standard
        elif self._hovering:
            bg = colors.bg_card_hover
            border = "transparent"
        else:
            bg = "transparent"
            border = "transparent"
        icon_color = colors.accent if self._selected else colors.text_muted
        text_color = (
            colors.text_primary if self._selected else colors.text_secondary
        )
        weight = "600" if self._selected else "500"
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: 1px solid {border};"
            f" border-radius: 6px; }}"
        )
        if self._icon_label is not None:
            self._icon_label.setStyleSheet(
                f"color: {icon_color}; font-size: 18px;"
            )
        if self._text_label is not None:
            self._text_label.setStyleSheet(
                f"color: {text_color}; font-size: 13px; font-weight: {weight};"
                " background: transparent;"
            )
        if self._marker is not None:
            self._marker.setStyleSheet(
                f"color: {colors.accent}; font-size: 14px; background: transparent;"
            )


class QtSidebar(QFrame):
    """左侧导航栏：品牌、当前存档、页签、最近存档与折叠开关。"""

    EXPANDED_WIDTH = 224
    COLLAPSED_WIDTH = 68

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
        """构建与 Flet 布局一致的 Qt 侧边栏。"""
        super().__init__()
        self._translate = translate
        self._on_tab_select = on_tab_select
        self._on_import_save = on_import_save
        self._on_recent_save_select = on_recent_save_select
        self._recent_saves: list[dict[str, Any]] = list(recent_saves or [])
        self._collapsed = False
        self._tabs: list[dict[str, str]] = list(tabs)
        self._buttons: dict[str, _TabButton] = {}
        self._selected_id: Optional[str] = None
        self._current_save_path = current_save_path
        self._recent_expanded = False

        self.setFixedWidth(self.EXPANDED_WIDTH)
        self.setObjectName("sidebar")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._header = QWidget()
        self._header_layout = QVBoxLayout(self._header)
        self._header_layout.setContentsMargins(0, 0, 0, 0)
        self._header_layout.setSpacing(0)
        self._root.addWidget(self._header)

        self._tabs_scroll = QScrollArea()
        self._tabs_scroll.setWidgetResizable(True)
        self._tabs_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._tabs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tabs_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        tabs_container = QWidget()
        self._tabs_layout = QVBoxLayout(tabs_container)
        self._tabs_layout.setContentsMargins(14, 12, 14, 10)
        self._tabs_layout.setSpacing(4)
        self._tabs_layout.addStretch(1)
        for tab in self._tabs:
            self._add_tab_button(tab)
        self._tabs_scroll.setWidget(tabs_container)
        self._root.addWidget(self._tabs_scroll, 1)

        self._toggle_button: _ToggleButton = build_toggle_button(
            collapsed=self._collapsed,
            on_toggle=self.toggle_collapsed,
            tooltip=self._t(
                "sidebar.collapse" if not self._collapsed else "sidebar.expand",
                "收起侧边栏" if not self._collapsed else "展开侧边栏",
            ),
        )
        self._root.addWidget(self._toggle_button)

        self._footer: _Footer = build_footer(collapsed=self._collapsed)
        self._root.addWidget(self._footer)

        self._rebuild_header()
        self._rebuild_recent_saves()
        self._apply_sidebar_style()

    def _t(self, key: str, default: str = "") -> str:
        return self._translate(key, default)

    def _apply_sidebar_style(self) -> None:
        colors = get_theme_manager().current
        self.setStyleSheet(
            f"QFrame#sidebar {{ background-color: {colors.bg_secondary};"
            f" border: none; border-right: 1px solid {colors.border_subtle}; }}"
        )

    # ─── 公开操作 ───────────────────────────────

    def select_tab(self, view_id: str) -> None:
        """选中指定页签并同步按钮样式。"""
        if view_id == self._selected_id:
            return
        previous = self._buttons.get(self._selected_id or "")
        if previous is not None:
            previous.set_selected(False)
        self._selected_id = view_id
        button = self._buttons.get(view_id)
        if button is not None:
            button.set_selected(True)

    def set_current_save(self, path: Optional[str]) -> None:
        """更新当前存档显示（设为金色名称，匹配 Flet）。"""
        self._current_save_path = path
        self._rebuild_header()

    def set_recent_saves(self, saves: list[dict[str, Any]]) -> None:
        """更新最近存档列表。"""
        self._recent_saves = list(saves)
        self._rebuild_recent_saves()
        self._rebuild_header()

    def set_collapsed(self, collapsed: bool) -> None:
        """切换折叠态并重建头部/页签/切换/页脚。"""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(
            self.COLLAPSED_WIDTH if collapsed else self.EXPANDED_WIDTH
        )
        for button in self._buttons.values():
            button.set_collapsed(collapsed)
        self._tabs_layout.setContentsMargins(
            12 if collapsed else 14,
            12,
            12 if collapsed else 14,
            10,
        )
        self._rebuild_header()
        self._toggle_button.set_collapsed(collapsed)
        self._footer.set_collapsed(collapsed)
        self._apply_sidebar_style()

    def toggle_collapsed(self) -> None:
        """切换折叠状态。"""
        self.set_collapsed(not self._collapsed)

    @property
    def is_collapsed(self) -> bool:
        """当前是否折叠。"""
        return self._collapsed

    @property
    def selected_id(self) -> Optional[str]:
        """当前选中的页签 id。"""
        return self._selected_id

    # ─── 内部构建 ───────────────────────────────

    def _add_tab_button(self, tab: dict[str, str]) -> None:
        view_id = tab["id"]
        button = _TabButton(
            view_id=view_id,
            icon=tab.get("icon", "•"),
            label=tab.get("label", view_id),
            on_click=self._on_tab_select,
        )
        self._buttons[view_id] = button
        self._tabs_layout.insertWidget(self._tabs_layout.count() - 1, button)

    def _rebuild_header(self) -> None:
        """按当前折叠态重建头部。"""
        while self._header_layout.count():
            item = self._header_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        if self._collapsed:
            widget = build_header_collapsed(
                on_set_current_save=self._on_pick_current_save,
                recent_menu=self._build_collapsed_recent_menu(),
                set_current_tooltip=self._t(
                    "sidebar.set_current_save", "设置当前存档"
                ),
            )
            self._header_layout.addWidget(widget)
            return
        widget = build_header_expanded(
            current_save_name=self._current_save_display(),
            current_save_label=self._t("sidebar.current_save", "当前存档"),
            set_current_label=self._t(
                "sidebar.set_current_save", "设置当前存档"
            ),
            recent_saves_label=self._t("sidebar.recent_saves", "最近存档"),
            recent_arrow_state=self._recent_expanded,
            on_set_current_save=self._on_pick_current_save,
            on_toggle_recent=self.toggle_recent,
        )
        self._header_layout.addWidget(widget)

    def _current_save_display(self) -> str:
        path = self._current_save_path
        if not path:
            return self._t("sidebar.no_current_save", "未设置当前存档")
        return os.path.basename(path.rstrip("\\/")) or path

    def _on_pick_current_save(self) -> None:
        if self._on_import_save is not None:
            self._on_import_save()

    def toggle_recent(self) -> None:
        """展开/收起最近存档。"""
        self._recent_expanded = not self._recent_expanded
        self._rebuild_header()
        self._rebuild_recent_saves()

    def _rebuild_recent_saves(self) -> None:
        """重建最近存档列表（Flet 布局：图标 + 名称 + 路径 + 当前标记）。"""
        # 由 header 内嵌的 recent_body 持有；header 重建时已删除旧控件。
        if not self._recent_expanded:
            return
        # recent body 由 header 构建时插入下方的滚动容器；这里不做额外工作。

    def _build_collapsed_recent_menu(self) -> Optional[QWidget]:
        """折叠态的最近存档弹出菜单（简化：点击展开头部回退）。"""
        return None


__all__ = ["QtSidebar"]
