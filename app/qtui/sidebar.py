"""Qt 任务分组侧边栏：世界工作区、安全、诊断与工具入口。"""
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
    build_brand_block,
    build_brand_box,
    build_footer,
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
        self._badge_text = ""
        self._icon_label: QLabel | None = None
        self._text_label: QLabel | None = None
        self._marker: QLabel | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        self.setToolTip(label)
        self.setMouseTracking(True)
        self._content_layout = QHBoxLayout(self)
        self._rebuild()

    def _clear_layout(self) -> None:
        self._icon_label = None
        self._text_label = None
        self._marker = None
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def _rebuild(self) -> None:
        """重建子控件与布局（折叠往返安全）。"""
        self._clear_layout()
        icon_label = QLabel(self._icon)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label = icon_label
        layout = self._content_layout
        if self._collapsed:
            self.setFixedWidth(44)
            layout.setContentsMargins(0, 0, 0, 0)
            icon_label.setFixedSize(44, 44)
            layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignCenter)
        else:
            # Qt 的 setFixedWidth() 同时锁定最大宽度；展开时必须显式解除。
            self.setMaximumWidth(16777215)
            self.setMinimumWidth(0)
            layout.setContentsMargins(10, 6, 10, 6)
            layout.setSpacing(8)
            icon_slot = QWidget()
            icon_slot.setFixedSize(28, 28)
            icon_layout = QHBoxLayout(icon_slot)
            icon_layout.setContentsMargins(0, 0, 0, 0)
            icon_layout.addStretch(1)
            icon_layout.addWidget(icon_label)
            icon_layout.addStretch(1)
            text_label = QLabel(self._label)
            text_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            self._text_label = text_label
            marker = QLabel("•")
            marker.setText(self._marker_text())
            marker.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
            self._marker = marker
            layout.addWidget(icon_slot)
            layout.addWidget(text_label, 1)
            layout.addWidget(marker)
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
            self._marker.setText(self._marker_text())
        self._apply_style()

    def set_badge(self, count: int) -> None:
        """显示待办数量；0 时恢复普通选中标记。"""
        self._badge_text = str(count) if count > 0 else ""
        if self._marker is not None:
            self._marker.setText(self._marker_text())
        suffix = f" ({count})" if count > 0 else ""
        self.setToolTip(f"{self._label}{suffix}")
        self._apply_style()

    def _marker_text(self) -> str:
        if self._badge_text:
            return self._badge_text
        return "•" if self._selected else ""

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
            if self._badge_text:
                self._marker.setStyleSheet(
                    f"color: {colors.text_invert}; font-size: 10px;"
                    f" background: {colors.accent}; border-radius: 7px;"
                    " padding: 1px 5px;"
                )
            else:
                self._marker.setStyleSheet(
                    f"color: {colors.accent}; font-size: 14px;"
                    " background: transparent;"
                )


class _GroupLabel(QLabel):
    """展开态显示的导航任务分组标题。"""

    def __init__(self, text: str) -> None:
        super().__init__(text.upper())
        self.setProperty("role", "navigationGroup")
        self.setContentsMargins(8, 8, 0, 2)


class QtSidebar(QFrame):
    """左侧导航栏：品牌、当前存档、页签、最近存档与折叠开关。"""

    EXPANDED_WIDTH = 208
    COLLAPSED_WIDTH = 64

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
        self._group_labels: list[_GroupLabel] = []
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
        current_group = ""
        footer_tabs: list[dict[str, str]] = []
        for tab in self._tabs:
            if tab.get("placement") == "footer":
                footer_tabs.append(tab)
                continue
            group = tab.get("group", "")
            if group and group != current_group:
                self._add_group_label(group)
                current_group = group
            self._add_tab_button(tab, self._tabs_layout)
        self._tabs_scroll.setWidget(tabs_container)
        self._root.addWidget(self._tabs_scroll, 1)

        # 布局：设置等应用级入口固定在侧栏底部，不随主导航滚动。
        self._utility_host = QWidget()
        self._utility_layout = QVBoxLayout(self._utility_host)
        self._utility_layout.setContentsMargins(14, 4, 14, 4)
        self._utility_layout.setSpacing(4)
        for tab in footer_tabs:
            self._add_tab_button(tab, self._utility_layout)
        self._root.addWidget(self._utility_host)

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
        """保留最近存档快照；菜单由世界上下文栏呈现。"""
        self._recent_saves = list(saves)

    def set_badge(self, navigation_id: str, count: int) -> None:
        """更新导航入口的待办数量徽标。"""
        button = self._buttons.get(navigation_id)
        if button is not None:
            button.set_badge(count)

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
            10 if collapsed else 12,
            12,
            10 if collapsed else 12,
            10,
        )
        self._utility_layout.setContentsMargins(
            10 if collapsed else 12,
            4,
            10 if collapsed else 12,
            4,
        )
        for label in self._group_labels:
            label.setVisible(not collapsed)
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

    def _add_group_label(self, text: str) -> None:
        label = _GroupLabel(text)
        self._group_labels.append(label)
        self._tabs_layout.insertWidget(self._tabs_layout.count() - 1, label)

    def _add_tab_button(
        self,
        tab: dict[str, str],
        layout: QVBoxLayout,
    ) -> None:
        view_id = tab["id"]
        button = _TabButton(
            view_id=view_id,
            icon=tab.get("icon", "•"),
            label=tab.get("label", view_id),
            on_click=self._on_tab_select,
        )
        self._buttons[view_id] = button
        if layout is self._tabs_layout:
            layout.insertWidget(layout.count() - 1, button)
        else:
            layout.addWidget(button)

    def _rebuild_header(self) -> None:
        """按当前折叠态重建头部。"""
        while self._header_layout.count():
            item = self._header_layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(12, 12, 12, 8)
        if self._collapsed:
            layout.addWidget(build_brand_box())
        else:
            layout.addWidget(build_brand_block())
        self._header_layout.addWidget(host)

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
