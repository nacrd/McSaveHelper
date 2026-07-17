"""Equipment Preview component - Minecraft 风格装备展示，支持纹理图片"""
import flet as ft
from typing import Any, Dict, List, Optional

from app.services.item_service import ItemService
from app.services.texture_service import TextureService
from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.ui.views.explorer.item_slot import (
    ItemSlotControl,
    create_item_slot,
    reset_item_slot,
    apply_item_to_slot,
    apply_texture_to_slot,
)


class EquipmentPreview(ft.Column):
    """玩家装备预览 - 展示头盔、胸甲、护腿、靴子和副手"""

    DEFAULT_EQUIP_SLOTS = {
        103: ("🪖", "头盔"),
        102: ("👕", "胸甲"),
        101: ("👖", "护腿"),
        100: ("👢", "靴子"),
        -106: ("🤚", "副手"),
    }

    def __init__(
        self,
        item_service: ItemService,
        texture_service: TextureService,
        slot_size: int = 48,
    ) -> None:
        super().__init__(spacing=4)
        self._slot_size = slot_size
        self._slot_rows: Dict[int, ft.Row] = {}
        self._slot_containers: Dict[int, ft.Container] = {}
        self._slot_controls: Dict[int, ItemSlotControl] = {}
        self._item_service = item_service
        self._texture_service = texture_service

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
            row = self._create_slot(nbt_slot, icon, label)
            self._slot_rows[nbt_slot] = row
            self.controls.append(row)

    def _create_slot(
            self,
            nbt_slot: int,
            slot_icon_emoji: str,
            label: str) -> ft.Row:
        slot = create_item_slot(self._slot_size, count_size=8)
        slot_container = slot.container

        slot_icon = ft.Text(slot_icon_emoji, size=14, color=THEME.text_muted)
        label_text = ft.Text(
            label, size=11, color=THEME.text_secondary,
            width=45,
            text_align=ft.TextAlign.CENTER,
        )

        self._slot_containers[nbt_slot] = slot_container
        self._slot_controls[nbt_slot] = slot

        return ft.Row(
            [slot_icon, label_text, slot_container, ft.Container(width=10)],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def set_equipment(self, inventory: List[Dict[str, Any]]) -> None:
        for nbt_slot in self._slot_order:
            container = self._slot_containers.get(nbt_slot)
            if container is None:
                continue
            reset_item_slot(self._slot_controls[nbt_slot])

        item_ids_to_load: Dict[int, str] = {}

        try:
            equip_slots_set = set(self._equip_slots.keys())
            for item in inventory:
                si = item.get("slot", -999)
                if si not in equip_slots_set:
                    continue

                container = self._slot_containers.get(si)
                if container is None:
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
        self._texture_service.load_textures_async(
            unique_ids, on_loaded=_on_loaded)

    def add_custom_slot(self, slot_id: int, icon: str, label: str) -> None:
        if slot_id in self._equip_slots:
            return

        self._equip_slots[slot_id] = (icon, label)
        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        row = self._create_slot(slot_id, icon, label)
        self._slot_rows[slot_id] = row

        self.controls = [self.controls[0]]
        for nbt_slot in self._slot_order:
            self.controls.append(self._slot_rows[nbt_slot])

        safe_update(self)

    def clear(self) -> None:
        self.set_equipment([])
