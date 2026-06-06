"""侧边栏导航组件（Linear 风格，支持拖拽排序）"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME


class Sidebar(ft.Container):
    """左侧导航栏，支持拖拽排序标签页"""

    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        default_tab: Optional[str] = None,
    ) -> None:
        self._tabs: List[Dict[str, Any]] = list(tabs)
        self._on_tab_select: Callable[[str], None] = on_tab_select
        self._on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = on_tabs_reorder
        self._selected_id: Optional[str] = default_tab or (tabs[0]["id"] if tabs else None)
        self._buttons: Dict[str, ft.Container] = {}
        self._tab_col: ft.Column = ft.Column(spacing=2)

        col = ft.Column(spacing=2)
        col.expand = True

        # Logo
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    "MCSaveHelper",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=THEME.accent,
                ),
                padding=ft.Padding(left=20, right=20, top=30, bottom=24),
            )
        )

        # 标签按钮容器（可拖拽排序）
        self._tab_col.expand = True
        self._rebuild_tab_buttons()
        col.controls.append(self._tab_col)

        # 弹性空间
        col.controls.append(ft.Container())
        col.controls[-1].expand = True

        # 版本号
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    "v1.0.0",
                    size=10,
                    color=THEME.text_quaternary,
                ),
                padding=ft.Padding(left=20, top=20, right=20, bottom=20),
            )
        )

        super().__init__(
            content=col,
            width=180,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None, top=None,
                right=ft.BorderSide(1, "rgba(255,255,255,0.05)"),
                bottom=None,
            ),
        )

    def _rebuild_tab_buttons(self) -> None:
        """根据 _tabs 顺序重建所有标签按钮"""
        self._tab_col.controls.clear()
        self._buttons.clear()
        for tab in self._tabs:
            btn = self._build_tab_button(tab)
            self._buttons[tab["id"]] = btn
            self._tab_col.controls.append(btn)

    def _build_tab_button(self, tab: Dict[str, Any]) -> ft.Container:
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "")
        label_text = tab.get("label", tab["id"])
        text_str = f"  {icon} {label_text}" if icon else f"  {label_text}"

        text_ctrl = ft.Text(
            text_str,
            size=13,
            color=THEME.text_primary if selected else THEME.text_secondary,
            weight=ft.FontWeight.W_500 if selected else ft.FontWeight.NORMAL,
        )
        indicator = ft.Container(
            width=4, height=24,
            bgcolor=THEME.accent if selected else None,
            border_radius=2,
        )

        row = ft.Row(
            [indicator, text_ctrl],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        container = ft.Container(
            content=row,
            padding=ft.Padding(left=16, top=10, right=16, bottom=10),
            border_radius=6,
            bgcolor=THEME.bg_card if selected else None,
            ink=True,
        )
        # 使用安全包装的事件回调，确保不会向 Flet 抛出异常
        container.on_click = lambda e, tid=tab["id"]: self._safe_select(tid)
        return container

    def _safe_select(self, tab_id: str) -> None:
        """安全的选择回调，捕获所有异常防止 UI 冻结"""
        try:
            self._select(tab_id)
        except Exception as e:
            traceback.print_exc()
            # 至少更新选中状态
            self._selected_id = tab_id

    def _select(self, tab_id: str) -> None:
        if tab_id == self._selected_id:
            return
        # 更新旧按钮样式
        if self._selected_id and self._selected_id in self._buttons:
            self._apply_style(self._buttons[self._selected_id], False)
        self._selected_id = tab_id
        # 更新新按钮样式
        if tab_id in self._buttons:
            self._apply_style(self._buttons[tab_id], True)
        try:
            self.update()
        except Exception:
            pass
        # 通知外部
        self._on_tab_select(tab_id)

    def _apply_style(self, container: ft.Container, selected: bool) -> None:
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            tc = row.controls[1]
            ind = row.controls[0]
            tc.color = THEME.text_primary if selected else THEME.text_secondary
            tc.weight = ft.FontWeight.W_500 if selected else ft.FontWeight.NORMAL
            ind.bgcolor = THEME.accent if selected else None
        container.bgcolor = THEME.bg_card if selected else None

    @property
    def selected_id(self) -> Optional[str]:
        return self._selected_id

    def select_tab(self, tab_id: str) -> None:
        self._safe_select(tab_id)

    def reorder_tabs(self, new_order: List[str]) -> None:
        """根据 ID 列表重新排序标签页"""
        tab_map = {t["id"]: t for t in self._tabs}
        new_tabs = []
        for tid in new_order:
            if tid in tab_map:
                new_tabs.append(tab_map[tid])
        for t in self._tabs:
            if t["id"] not in new_order:
                new_tabs.append(t)
        self._tabs = new_tabs
        self._rebuild_tab_buttons()
        try:
            self._tab_col.update()
        except Exception:
            pass
        if self._on_tabs_reorder:
            try:
                self._on_tabs_reorder(self._tabs)
            except Exception:
                traceback.print_exc()

    def get_tab_order(self) -> List[str]:
        """返回当前标签页 ID 的顺序"""
        return [t["id"] for t in self._tabs]
