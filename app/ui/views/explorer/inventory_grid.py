"""Inventory Grid component"""
import flet as ft
from typing import Any, Dict, List

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update


class InventoryGrid(ft.Column):
    """Minecraft 原版物品栏布局：3×9 主物品栏 + 间隔 + 1×9 快捷栏"""

    SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
    SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
    SLOT_BG_EMPTY = "#2a2a2e"
    SLOT_BG_FILLED = "#3a3a3e"

    def __init__(self, slot_size: int = 44) -> None:
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._item_tags: Dict[int, Any] = {}

        def make_slot_border():
            return ft.Border(
                left=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                top=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                right=ft.BorderSide(2, self.SLOT_BORDER_DARK),
                bottom=ft.BorderSide(2, self.SLOT_BORDER_DARK),
            )

        def make_slot(nbt_slot: int) -> ft.Container:
            inner = ft.Column(
                [
                    ft.Text("", size=8, color=THEME.text_muted, text_align=ft.TextAlign.CENTER),
                    ft.Text("", size=10, color="#ccc", weight=ft.FontWeight.BOLD,
                            text_align=ft.TextAlign.RIGHT),
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            )
            s = ft.Container(
                width=slot_size,
                height=slot_size,
                bgcolor=self.SLOT_BG_EMPTY,
                border=make_slot_border(),
                border_radius=2,
                padding=2,
                alignment=ft.alignment.center,
                content=inner,
            )
            self._slots[nbt_slot] = s
            return s

        main_rows: List[ft.Control] = []
        for row in range(3):
            slots_row = [make_slot(9 + row * 9 + col) for col in range(9)]
            main_rows.append(ft.Row(slots_row, spacing=2, alignment=ft.MainAxisAlignment.START))

        hotbar_slots = [make_slot(col) for col in range(9)]
        hotbar_row = ft.Row(hotbar_slots, spacing=2, alignment=ft.MainAxisAlignment.START)

        self.controls = [
            ft.Text("主物品栏", size=12, color=THEME.text_muted),
            *main_rows,
            ft.Container(height=8),
            ft.Text("快捷栏", size=12, color=THEME.text_muted),
            hotbar_row,
        ]

    def set_inventory(self, inventory: List[Dict[str, Any]]) -> None:
        for nbt_slot, s in self._slots.items():
            s.bgcolor = self.SLOT_BG_EMPTY
            inner = s.content
            if isinstance(inner, ft.Column) and len(inner.controls) >= 2:
                inner.controls[0].value = ""
                inner.controls[0].color = THEME.text_muted
                inner.controls[1].value = ""

        self._item_tags.clear()
        try:
            for item in inventory:
                si = item.get("slot", -1)
                if not 0 <= si < 36:
                    continue
                s = self._slots.get(si)
                if s is None:
                    continue
                s.bgcolor = self.SLOT_BG_FILLED
                self._item_tags[si] = item.get("tag")
                c = item.get("count", 1)
                iid = item.get("id", "")
                dn = iid.split(":")[-1] if ":" in iid else iid
                inner = s.content
                if isinstance(inner, ft.Column) and len(inner.controls) >= 2:
                    inner.controls[0].value = dn
                    inner.controls[0].color = THEME.text_primary
                    inner.controls[1].value = f"×{c}" if c > 1 else ""
                    inner.controls[1].color = "#aaa"
        except Exception:
            pass
        safe_update(self)

    def clear(self) -> None:
        self.set_inventory([])