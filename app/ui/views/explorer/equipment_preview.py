"""Equipment Preview component - Minecraft 风格装备展示，支持纹理图片"""
import flet as ft
from typing import Any, Dict, List, Optional

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.services.item_service import get_item_service, ItemInfo
from app.services.texture_service import get_texture_service


class EquipmentPreview(ft.Column):
    """玩家装备预览 - 展示头盔、胸甲、护腿、靴子和副手"""

    SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
    SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
    SLOT_BG_EMPTY = "#2a2a2e"
    SLOT_BG_FILLED = "#3a3a3e"

    DURABILITY_HIGH = "#4CAF50"
    DURABILITY_MEDIUM = "#FF9800"
    DURABILITY_LOW = "#F44336"
    ENCHANTMENT_COLOR = "#7B68EE"

    DEFAULT_EQUIP_SLOTS = {
        103: ("🪖", "头盔"),
        102: ("👕", "胸甲"),
        101: ("👖", "护腿"),
        100: ("👢", "靴子"),
        -106: ("🤚", "副手"),
    }

    def __init__(self, slot_size: int = 48) -> None:
        super().__init__(spacing=4)
        self._slot_size = slot_size
        self._img_size = int(slot_size * 0.65)
        self._slot_rows: Dict[int, ft.Row] = {}
        self._slot_containers: Dict[int, ft.Container] = {}
        self._slot_images: Dict[int, ft.Image] = {}
        self._slot_count_texts: Dict[int, ft.Text] = {}
        self._slot_dur_texts: Dict[int, ft.Text] = {}
        self._slot_ench_texts: Dict[int, ft.Text] = {}
        self._item_service = get_item_service()
        self._texture_service = get_texture_service()

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

    def _create_slot(self, nbt_slot: int, icon: str, label: str) -> ft.Row:
        img = ft.Image(
            src="",
            width=self._img_size,
            height=self._img_size,
            fit="contain",
            visible=False,
        )
        count_text = ft.Text(
            "", size=8, color="#ddd",
            text_align=ft.TextAlign.RIGHT,
            weight=ft.FontWeight.BOLD,
        )
        dur_text = ft.Text("", size=6, color=self.DURABILITY_HIGH, text_align=ft.TextAlign.CENTER)
        ench_text = ft.Text("", size=7, color=self.ENCHANTMENT_COLOR, text_align=ft.TextAlign.LEFT)

        stack = ft.Stack(
            [
                ft.Container(
                    content=img,
                    alignment=ft.alignment.Alignment(0, 0),
                    width=self._slot_size,
                    height=self._slot_size,
                ),
                ft.Container(
                    content=count_text,
                    alignment=ft.alignment.Alignment(1, 1),
                    padding=ft.Padding(0, 0, 2, 0),
                    width=self._slot_size,
                    height=self._slot_size,
                ),
                ft.Container(
                    content=ench_text,
                    alignment=ft.alignment.Alignment(-1, -1),
                    padding=ft.Padding(2, 0, 0, 0),
                    width=self._slot_size,
                    height=self._slot_size,
                ),
                ft.Container(
                    content=dur_text,
                    alignment=ft.alignment.Alignment(0, 1),
                    padding=ft.Padding(0, 0, 0, 1),
                    width=self._slot_size,
                    height=self._slot_size,
                ),
            ],
            width=self._slot_size,
            height=self._slot_size,
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
            padding=0,
            content=stack,
        )

        slot_icon = ft.Text(icon, size=14, color=THEME.text_muted)
        label_text = ft.Text(
            label, size=11, color=THEME.text_secondary,
            width=45,
            text_align=ft.TextAlign.CENTER,
        )

        self._slot_containers[nbt_slot] = slot_container
        self._slot_images[nbt_slot] = img
        self._slot_count_texts[nbt_slot] = count_text
        self._slot_dur_texts[nbt_slot] = dur_text
        self._slot_ench_texts[nbt_slot] = ench_text

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
            container.bgcolor = self.SLOT_BG_EMPTY
            container.tooltip = None
            self._slot_images[nbt_slot].visible = False
            self._slot_images[nbt_slot].src = ""
            self._slot_count_texts[nbt_slot].value = ""
            self._slot_dur_texts[nbt_slot].value = ""
            self._slot_ench_texts[nbt_slot].value = ""

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

                container.bgcolor = self.SLOT_BG_FILLED
                container.tooltip = self._item_service.format_item_tooltip(item_info)

                count_text = self._slot_count_texts[si]
                dur_text = self._slot_dur_texts[si]
                ench_text = self._slot_ench_texts[si]

                count_text.value = f"×{item_info.count}" if item_info.count > 1 else ""

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
                    dur_text.value = "█" * filled + "░" * (bar_len - filled)
                    dur_text.color = dur_color

                if item_info.enchantments:
                    ench_text.value = "✦" * min(len(item_info.enchantments), 3)
                    ench_text.color = self.ENCHANTMENT_COLOR

                if item_info.id:
                    item_ids_to_load[si] = item_info.id

        except Exception:
            pass

        safe_update(self)

        if item_ids_to_load:
            self._load_textures_async(item_ids_to_load)

    def _load_textures_async(self, slot_item_map: Dict[int, str]) -> None:
        def _on_loaded(item_id: str, uri: Optional[str]):
            if uri is None:
                return
            for slot_idx, iid in slot_item_map.items():
                if iid == item_id:
                    img = self._slot_images.get(slot_idx)
                    if img is not None:
                        img.src = uri
                        img.visible = True
                        safe_update(img)

        unique_ids = list(set(slot_item_map.values()))
        self._texture_service.load_textures_async(unique_ids, on_loaded=_on_loaded)

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
