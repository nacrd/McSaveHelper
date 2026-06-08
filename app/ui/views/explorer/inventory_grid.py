"""Inventory Grid component - Minecraft 风格物品栏，支持纹理图片"""
import flet as ft
from typing import Any, Dict, List, Optional

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.services.item_service import get_item_service
from app.services.texture_service import get_texture_service
from app.ui.views.explorer.item_slot import (
    ItemSlotControl,
    create_item_slot,
    reset_item_slot,
    apply_item_to_slot,
    apply_texture_to_slot,
)


class InventoryGrid(ft.Column):
    """Minecraft 原版物品栏布局：3×9 主物品栏 + 间隔 + 1×9 快捷栏"""

    def __init__(self, slot_size: int = 48) -> None:
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._slot_controls: Dict[int, ItemSlotControl] = {}
        self._item_service = get_item_service()
        self._texture_service = get_texture_service()

        def make_slot(nbt_slot: int) -> ft.Container:
            slot = create_item_slot(slot_size)
            s = slot.container
            self._slots[nbt_slot] = s
            self._slot_controls[nbt_slot] = slot
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
            reset_item_slot(self._slot_controls[nbt_slot])

        item_ids_to_load: Dict[int, str] = {}

        try:
            for item in inventory:
                si = item.get("slot", -1)
                if not 0 <= si < 36:
                    continue
                s = self._slots.get(si)
                if s is None:
                    continue

                item_info = self._item_service.parse_item(item)
                apply_item_to_slot(
                    self._slot_controls[si],
                    item_info,
                    self._item_service.format_item_tooltip(item_info),
                )

                if item_info.id:
                    item_ids_to_load[si] = item_info.id

        except Exception:
            pass

        safe_update(self)

        # 异步加载真实纹理
        if item_ids_to_load:
            self._load_textures_async(item_ids_to_load)

    def _load_textures_async(self, slot_item_map: Dict[int, str]) -> None:
        """异步加载纹理，成功后隐藏 Emoji，显示图片"""
        def _on_loaded(item_id: str, uri: Optional[str]):
            if uri is None:
                return
            for slot_idx, iid in slot_item_map.items():
                if iid == item_id:
                    slot = self._slot_controls.get(slot_idx)
                    if slot is not None:
                        apply_texture_to_slot(slot, uri)

        unique_ids = list(set(slot_item_map.values()))
        self._texture_service.load_textures_async(unique_ids, on_loaded=_on_loaded)

    def clear(self) -> None:
        self.set_inventory([])
