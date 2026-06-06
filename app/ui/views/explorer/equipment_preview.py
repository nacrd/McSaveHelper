"""Equipment Preview component - Minecraft 风格装备展示"""
import flet as ft
from typing import Any, Dict, List, Optional

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.services.item_service import get_item_service, ItemInfo


class EquipmentPreview(ft.Column):
    """玩家装备预览 - 展示头盔、胸甲、护腿、靴子和副手"""

    SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
    SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
    SLOT_BG_EMPTY = "#2a2a2e"
    SLOT_BG_FILLED = "#3a3a3e"

    # 耐久度颜色
    DURABILITY_HIGH = "#4CAF50"
    DURABILITY_MEDIUM = "#FF9800"
    DURABILITY_LOW = "#F44336"
    ENCHANTMENT_COLOR = "#7B68EE"

    # 默认装备槽位
    DEFAULT_EQUIP_SLOTS = {
        103: ("🪖", "头盔"),
        102: ("👕", "胸甲"),
        101: ("👖", "护腿"),
        100: ("👢", "靴子"),
        -106: ("🤚", "副手"),
    }

    def __init__(self, slot_size: int = 44) -> None:
        super().__init__(spacing=4)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._item_service = get_item_service()

        # 合并默认槽位和自定义槽位
        self._equip_slots = dict(self.DEFAULT_EQUIP_SLOTS)
        custom_slots = self._item_service.get_custom_slots()
        for slot_id, name in custom_slots.items():
            if slot_id not in self._equip_slots:
                self._equip_slots[slot_id] = ("📦", name)

        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        self.controls.append(
            ft.Text("装备栏", size=12, color=THEME.text_muted)
        )

        for nbt_slot in self._slot_order:
            icon, label = self._equip_slots[nbt_slot]
            slot_container = self._create_slot(nbt_slot, icon, label)
            self._slots[nbt_slot] = slot_container
            self.controls.append(slot_container)

    def _create_slot(self, nbt_slot: int, icon: str, label: str) -> ft.Container:
        """创建单个装备槽"""
        name_text = ft.Text(
            "", size=9, color=THEME.text_muted,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        count_text = ft.Text("", size=8, color="#aaa", text_align=ft.TextAlign.RIGHT)
        dur_text = ft.Text("", size=7, color=self.DURABILITY_HIGH, text_align=ft.TextAlign.CENTER)
        ench_text = ft.Text("", size=6, color=self.ENCHANTMENT_COLOR, text_align=ft.TextAlign.CENTER)

        inner = ft.Column(
            [name_text, count_text, dur_text, ench_text],
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        slot_icon = ft.Text(icon, size=14, color=THEME.text_muted)
        label_text = ft.Text(
            label, size=11, color=THEME.text_secondary,
            width=45,
            text_align=ft.TextAlign.CENTER,
        )

        slot_container = ft.Container(
            width=self._slot_size,
            height=self._slot_size,
            bgcolor=self.SLOT_BG_EMPTY,
            border=ft.Border(
                left=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                top=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                right=ft.BorderSide(2, self.SLOT_BORDER_DARK),
                bottom=ft.BorderSide(2, self.SLOT_BORDER_DARK),
            ),
            border_radius=2,
            padding=1,
            content=inner,
        )

        return ft.Row(
            [slot_icon, label_text, slot_container, ft.Container(width=10)],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def set_equipment(self, inventory: List[Dict[str, Any]]) -> None:
        """从物品栏数据中提取并显示装备"""
        # 清空所有槽位
        for nbt_slot in self._slot_order:
            row = self._slots[nbt_slot]
            slot_container = row.controls[2]
            slot_container.bgcolor = self.SLOT_BG_EMPTY
            slot_container.tooltip = None
            inner = slot_container.content
            if isinstance(inner, ft.Column) and len(inner.controls) >= 4:
                for ctrl in inner.controls:
                    ctrl.value = ""

        try:
            equip_slots_set = set(self._equip_slots.keys())
            for item in inventory:
                si = item.get("slot", -999)
                if si not in equip_slots_set:
                    continue

                row = self._slots.get(si)
                if row is None:
                    continue

                # 使用 ItemService 解析物品
                item_info = self._item_service.parse_item(item)

                slot_container = row.controls[2]
                slot_container.bgcolor = self.SLOT_BG_FILLED
                slot_container.tooltip = self._item_service.format_item_tooltip(item_info)

                inner = slot_container.content
                if isinstance(inner, ft.Column) and len(inner.controls) >= 4:
                    name_ctrl = inner.controls[0]
                    count_ctrl = inner.controls[1]
                    dur_ctrl = inner.controls[2]
                    ench_ctrl = inner.controls[3]

                    # 物品名称
                    name_ctrl.value = item_info.display_name[:8]
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

    def add_custom_slot(self, slot_id: int, icon: str, label: str) -> None:
        """动态添加自定义装备槽位"""
        if slot_id in self._equip_slots:
            return

        self._equip_slots[slot_id] = (icon, label)
        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        slot_container = self._create_slot(slot_id, icon, label)
        self._slots[slot_id] = slot_container

        # 重新构建 controls
        self.controls = [self.controls[0]]  # 保留标题
        for nbt_slot in self._slot_order:
            self.controls.append(self._slots[nbt_slot])

        safe_update(self)

    def clear(self) -> None:
        """清空装备显示"""
        self.set_equipment([])