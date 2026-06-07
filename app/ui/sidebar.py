"""Minecraft-style sidebar navigation component with drag-and-drop support and hover effects"""
import traceback
from typing import Callable, List, Dict, Any, Optional

import flet as ft

from app.ui.theme import THEME, mc_border
from core.version import APP_VERSION


class Sidebar(ft.Container):
    """Left navigation sidebar with drag-and-drop tab reordering and hover effects"""

    def __init__(
        self,
        tabs: List[Dict[str, Any]],
        on_tab_select: Callable[[str], None],
        on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
        on_import_save: Optional[Callable[[], None]] = None,
        on_set_current_save: Optional[Callable[[], None]] = None,
        on_recent_save_select: Optional[Callable[[str], None]] = None,
        recent_saves: Optional[List[Dict[str, Any]]] = None,
        default_tab: Optional[str] = None,
        width: int = 210,
    ) -> None:
        self._tabs: List[Dict[str, Any]] = list(tabs)
        self._on_tab_select: Callable[[str], None] = on_tab_select
        self._on_tabs_reorder: Optional[Callable[[List[Dict[str, Any]]], None]] = on_tabs_reorder
        # 保留 on_import_save 作为兼容回调；新 UI 语义为“设置当前存档”
        self._on_import_save: Optional[Callable[[], None]] = on_import_save
        self._on_set_current_save: Optional[Callable[[], None]] = on_set_current_save
        self._on_recent_save_select: Optional[Callable[[str], None]] = on_recent_save_select
        self._recent_saves: List[Dict[str, Any]] = list(recent_saves or [])
        self._selected_id: Optional[str] = default_tab or (tabs[0]["id"] if tabs else None)
        self._buttons: Dict[str, ft.Container] = {}
        self._recent_save_col: ft.Column = ft.Column(spacing=4)
        self._sidebar_width = width
        # 使用 ListView 替代 Column 实现滚动功能
        self._tab_col: ft.ListView = ft.ListView(
            spacing=6,
            padding=0,
            expand=True,
            auto_scroll=False,
        )
        self._current_save_name = ft.Text(
            "未设置当前存档",
            size=10,
            color=THEME.text_muted,
            font_family="monospace",
            no_wrap=True,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        self._rebuild_recent_saves()

        col = ft.Column(spacing=0, expand=True)

        # Header
        col.controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "⛏ MCSaveHelper",
                            size=16,
                            weight=ft.FontWeight.BOLD,
                            color=THEME.mc_gold,
                            font_family="monospace",
                        ),
                        ft.Text(
                            "Minecraft Save Toolkit",
                            size=9,
                            color=THEME.text_muted,
                            font_family="monospace",
                        ),
                        # 设置当前存档按钮
                        ft.Container(
                            content=ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Text("💾", size=14),
                                        ft.Text(
                                            "设置当前存档",
                                            size=11,
                                            weight=ft.FontWeight.W_500,
                                        ),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                alignment=ft.Alignment(0, 0),
                                padding=ft.Padding(left=8, right=8, top=6, bottom=6),
                                border_radius=4,
                                bgcolor=THEME.mc_grass,
                                border=mc_border(1),
                                ink=True,
                                on_click=self._handle_set_current_save,
                            ),
                            padding=ft.Padding(left=0, right=0, top=8, bottom=0),
                        ),
                        ft.Container(
                            content=self._current_save_name,
                            padding=ft.Padding(left=2, right=2, top=6, bottom=0),
                        ),
                        ft.Container(
                            content=ft.Column(
                                [
                                    ft.Text(
                                        "最近存档",
                                        size=10,
                                        weight=ft.FontWeight.BOLD,
                                        color=THEME.text_secondary,
                                        font_family="monospace",
                                    ),
                                    self._recent_save_col,
                                ],
                                spacing=5,
                            ),
                            padding=ft.Padding(left=0, right=0, top=10, bottom=0),
                        ),
                    ],
                    spacing=2,
                ),
                padding=ft.Padding(left=16, right=16, top=16, bottom=16),
                bgcolor=THEME.mc_dirt,
                border=ft.Border(
                    left=None,
                    top=None,
                    right=None,
                    bottom=ft.BorderSide(3, THEME.mc_grass),
                ),
            )
        )

        # Tab buttons - 使用滚动区域
        self._rebuild_tab_buttons()
        col.controls.append(
            ft.Container(
                content=self._tab_col,
                padding=ft.Padding(left=10, right=10, top=12, bottom=10),
                expand=True,
            )
        )

        # Footer
        col.controls.append(
            ft.Container(
                content=ft.Text(
                    f"{APP_VERSION}  ▣ stone edition",
                    size=9,
                    color=THEME.text_muted,
                    font_family="monospace",
                ),
                padding=ft.Padding(left=16, top=14, right=16, bottom=16),
                bgcolor=THEME.bg_secondary,
            )
        )

        super().__init__(
            content=col,
            width=width,
            bgcolor=THEME.bg_primary,
            border=ft.Border(
                left=None,
                top=None,
                right=ft.BorderSide(3, THEME.bg_secondary),
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
        """构建单个标签按钮 with hover effects"""
        selected = tab["id"] == self._selected_id
        icon = tab.get("icon", "▣")
        label_text = tab.get("label", tab["id"])

        icon_slot = ft.Container(
            content=ft.Text(
                icon,
                size=16,
                color=THEME.text_primary,
                text_align=ft.TextAlign.CENTER,
            ),
            width=36,
            height=36,
            alignment=ft.alignment.Alignment(0, 0),
            bgcolor=THEME.mc_gold if selected else THEME.bg_secondary,
            border=mc_border(2),
        )
        
        text_ctrl = ft.Text(
            label_text,
            size=12,
            color=THEME.text_primary if selected else THEME.text_secondary,
            weight=ft.FontWeight.BOLD if selected else ft.FontWeight.W_500,
            font_family="monospace",
        )
        
        marker = ft.Text(
            "▶" if selected else "",
            size=10,
            color=THEME.mc_grass,
        )

        row = ft.Row(
            [icon_slot, ft.Column([text_ctrl, marker], spacing=0)],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        
        container = ft.Container(
            content=row,
            padding=8,
            border_radius=0,
            bgcolor=THEME.mc_stone if selected else THEME.bg_card,
            border=mc_border(2),
            ink=True,
            on_click=lambda e, tid=tab["id"]: self._safe_select(tid),
            on_hover=lambda e, tid=tab["id"]: self._handle_hover(e, tid),
        )
        
        return container
    
    def _handle_hover(self, e: ft.ControlEvent, tab_id: str) -> None:
        """Handle hover event for tab buttons
        
        Args:
            e: Control event
            tab_id: Tab ID
        """
        try:
            if tab_id not in self._buttons:
                return
            
            container = self._buttons[tab_id]
            is_selected = tab_id == self._selected_id
            
            if e.data == "true":
                # Hover state - brighter background and enhanced shadow
                if not is_selected:
                    container.bgcolor = THEME.bg_card_hover
                    container.shadow = ft.BoxShadow(
                        spread_radius=0,
                        blur_radius=4,
                        color=THEME.shadow,
                        offset=ft.Offset(2, 2),
                    )
                    # Brighten icon slot
                    row = container.content
                    if isinstance(row, ft.Row) and len(row.controls) >= 1:
                        icon_slot = row.controls[0]
                        if isinstance(icon_slot, ft.Container):
                            icon_slot.bgcolor = THEME.mc_iron  # Brighter gray
            else:
                # Normal state - reset to original
                if not is_selected:
                    container.bgcolor = THEME.bg_card
                    container.shadow = None
                    # Reset icon slot
                    row = container.content
                    if isinstance(row, ft.Row) and len(row.controls) >= 1:
                        icon_slot = row.controls[0]
                        if isinstance(icon_slot, ft.Container):
                            icon_slot.bgcolor = THEME.bg_secondary
            
            container.update()
        except Exception:
            pass

    def _safe_select(self, tab_id: str) -> None:
        """安全的选择回调，捕获所有异常防止 UI 冻结"""
        try:
            self._select(tab_id)
        except Exception as e:
            traceback.print_exc()
            # 至少更新选中状态
            self._selected_id = tab_id

    def _handle_set_current_save(self, e: ft.ControlEvent) -> None:
        """处理设置当前存档按钮点击"""
        try:
            if self._on_set_current_save:
                self._on_set_current_save()
            elif self._on_import_save:
                self._on_import_save()
        except Exception:
            pass

    def _handle_import_save(self, e: ft.ControlEvent) -> None:
        """兼容旧入口：处理设置当前存档按钮点击"""
        self._handle_set_current_save(e)

    def _rebuild_recent_saves(self) -> None:
        """重建最近存档列表"""
        self._recent_save_col.controls.clear()
        if not self._recent_saves:
            self._recent_save_col.controls.append(
                ft.Text(
                    "暂无最近存档",
                    size=9,
                    color=THEME.text_muted,
                    font_family="monospace",
                )
            )
            return

        for save in self._recent_saves[:5]:
            self._recent_save_col.controls.append(self._build_recent_save_item(save))

    def _build_recent_save_item(self, save: Dict[str, Any]) -> ft.Container:
        """构建最近存档列表项"""
        save_id = str(save.get("id") or save.get("path") or save.get("name") or "")
        save_name = str(save.get("name") or save.get("label") or save_id or "未命名存档")
        save_path = str(save.get("path") or save_id)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Text("▣", size=9, color=THEME.mc_grass),
                    ft.Text(
                        save_name,
                        size=9,
                        color=THEME.text_secondary,
                        font_family="monospace",
                        no_wrap=True,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                ],
                spacing=5,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding(left=6, right=6, top=4, bottom=4),
            border_radius=3,
            bgcolor=THEME.bg_secondary,
            border=mc_border(1),
            ink=True,
            tooltip=save_path,
            on_click=lambda e, sid=save_id: self._safe_select_recent_save(sid),
        )

    def _safe_select_recent_save(self, save_id: str) -> None:
        """安全触发最近存档点击回调"""
        if not save_id:
            return
        try:
            if self._on_recent_save_select:
                self._on_recent_save_select(save_id)
        except Exception:
            traceback.print_exc()

    def set_recent_saves(self, saves: Optional[List[Dict[str, Any]]]) -> None:
        """更新最近存档列表"""
        self._recent_saves = list(saves or [])
        self._rebuild_recent_saves()
        try:
            self._recent_save_col.update()
        except Exception:
            pass

    def set_current_save_name(self, name: Optional[str], path: Optional[str] = None) -> None:
        try:
            if name:
                self._current_save_name.value = f"当前存档: {name}"
                self._current_save_name.color = THEME.mc_gold
                self._current_save_name.tooltip = path or name
            else:
                self._current_save_name.value = "未设置当前存档"
                self._current_save_name.color = THEME.text_muted
                self._current_save_name.tooltip = None
            self._current_save_name.update()
        except Exception:
            pass

    def _select(self, tab_id: str) -> None:
        """选择标签页"""
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
        """应用选中/未选中样式"""
        row = container.content
        if isinstance(row, ft.Row) and len(row.controls) >= 2:
            icon_slot = row.controls[0]
            text_group = row.controls[1]
            if isinstance(icon_slot, ft.Container):
                icon_slot.bgcolor = THEME.mc_gold if selected else THEME.bg_secondary
            if isinstance(text_group, ft.Column) and len(text_group.controls) >= 2:
                tc = text_group.controls[0]
                marker = text_group.controls[1]
                tc.color = THEME.text_primary if selected else THEME.text_secondary
                tc.weight = ft.FontWeight.BOLD if selected else ft.FontWeight.W_500
                marker.value = "▶" if selected else ""
        container.bgcolor = THEME.mc_stone if selected else THEME.bg_card

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
    
    def set_width(self, width: int) -> None:
        """动态设置侧边栏宽度
        
        Args:
            width: 新的侧边栏宽度
        """
        try:
            # 限制最小和最大宽度
            self._sidebar_width = max(160, min(300, width))
            self.width = self._sidebar_width
            self.update()
        except Exception:
            pass
    
    @property
    def sidebar_width(self) -> int:
        """获取当前侧边栏宽度"""
        return self._sidebar_width
