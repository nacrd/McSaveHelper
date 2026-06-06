"""Inventory Grid component"""
import flet as ft
from typing import Any, Dict, List

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.services.item_service import get_item_service, ItemInfo


class InventoryGrid(ft.Column):
    """Minecraft 原版物品栏布局：3×9 主物品栏 + 间隔 + 1×9 快捷栏"""

    SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
    SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
    SLOT_BG_EMPTY = "#2a2a2e"
    SLOT_BG_FILLED = "#3a3a3e"

    # 耐久度颜色
    DURABILITY_HIGH = "#4CAF50"    # 绿色 > 60%
    DURABILITY_MEDIUM = "#FF9800"  # 橙色 30-60%
    DURABILITY_LOW = "#F44336"     # 红色 < 30%
    ENCHANTMENT_COLOR = "#7B68EE"  # 紫色

    def __init__(self, slot_size: int = 44) -> None:
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._item_service = get_item_service()

        def make_slot_border():
            return ft.Border(
                left=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                top=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                right=ft.BorderSide(2, self.SLOT_BORDER_DARK),
                bottom=ft.BorderSide(2, self.SLOT_BORDER_DARK),
            )

        def make_slot(nbt_slot: int) -> ft.Container:
            name_text = ft.Text("", size=8, color=THEME.text_muted, text_align=ft.TextAlign.CENTER)
            count_text = ft.Text("", size=9, color="#aaa", text_align=ft.TextAlign.RIGHT)
            dur_text = ft.Text("", size=7, color=self.DURABILITY_HIGH, text_align=ft.TextAlign.CENTER)
            ench_text = ft.Text("", size=6, color=self.ENCHANTMENT_COLOR, text_align=ft.TextAlign.CENTER)

            inner = ft.Column(
                [name_text, count_text, dur_text, ench_text],
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
                padding=1,
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
        # 清空所有槽位
        for nbt_slot, s in self._slots.items():
            s.bgcolor = self.SLOT_BG_EMPTY
            s.tooltip = None
            inner = s.content
            if isinstance(inner, ft.Column) and len(inner.controls) >= 4:
                for ctrl in inner.controls:
                    ctrl.value = ""

        try:
            for item in inventory:
                si = item.get("slot", -1)
                if not 0 <= si < 36:
                    continue
                s = self._slots.get(si)
                if s is None:
                    continue

                # 使用 ItemService 解析物品
                item_info = self._item_service.parse_item(item)
                s.bgcolor = self.SLOT_BG_FILLED

                # 设置工具提示
                s.tooltip = self._item_service.format_item_tooltip(item_info)

                inner = s.content
                if isinstance(inner, ft.Column) and len(inner.controls) >= 4:
                    name_ctrl = inner.controls[0]
                    count_ctrl = inner.controls[1]
                    dur_ctrl = inner.controls[2]
                    ench_ctrl = inner.controls[3]

                    # 物品名称（截断显示）
                    name_ctrl.value = item_info.display_name[:6]
                    name_ctrl.color = THEME.text_primary

                    # 数量
                    count_ctrl.value = f"×{item_info.count}" if item_info.count > 1 else ""

                    # 耐久度
                    if item_info.durability_percent is not None:
                        percent = item_info.durability_percent
                        if percent > 60:
                            dur_color = self.DURABILITY_HIGH
                        elif percent > 30:
                            dur_color = self.DURABILITY_MEDIUM
                        else:
                            dur_color = self.DURABILITY_LOW
                        bar_len = 6
                        filled = int(percent / 100 * bar_len)
                        dur_ctrl.value = "█" * filled + "░" * (bar_len - filled)
                        dur_ctrl.color = dur_color

                    # 附魔标记
                    if item_info.enchantments:
                        ench_ctrl.value = "✦" * min(len(item_info.enchantments), 3)
                        ench_ctrl.color = self.ENCHANTMENT_COLOR

        except Exception:
            pass
        safe_update(self)

    def clear(self) -> None:
        self.set_inventory([])