"""Equipment Preview component - armor + offhand with textures."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, cast

import flet as ft

from app.services.item_service import ItemService
from app.services.texture_service import TextureService
from app.ui.theme import THEME
from app.ui.utils import run_on_ui
from app.ui.views.explorer.item_slot import (
    ItemSlotControl,
    apply_item_to_slot,
    apply_texture_to_slot,
    create_item_slot,
    reset_item_slot,
)
from app.ui.views.explorer.utils import safe_update

Translate = Callable[..., str]


class EquipmentPreview(ft.Column):
    """Player equipment preview - helmet/chest/legs/boots/offhand."""

    DEFAULT_EQUIP_SLOTS = {
        103: ("🪖", "player.equip.helmet", "头盔"),
        102: ("👕", "player.equip.chest", "胸甲"),
        101: ("👖", "player.equip.legs", "护腿"),
        100: ("👢", "player.equip.boots", "靴子"),
        -106: ("🤚", "player.equip.offhand", "副手"),
    }

    def __init__(
        self,
        item_service: ItemService,
        texture_service: TextureService,
        slot_size: int = 48,
        *,
        t_cb: Optional[Translate] = None,
    ) -> None:
        super().__init__(spacing=4)
        self._slot_size = slot_size
        self._slot_rows: Dict[int, ft.Column] = {}
        self._slot_containers: Dict[int, ft.Container] = {}
        self._slot_controls: Dict[int, ItemSlotControl] = {}
        self._item_service = item_service
        self._texture_service = texture_service
        self._texture_generation = 0
        self._slot_item_ids: Dict[int, str] = {}
        self._t = t_cb or (lambda key, default="", **_kw: default or key)

        self._equip_slots: Dict[int, tuple[str, str]] = {}
        for slot_id, (icon, key, default) in self.DEFAULT_EQUIP_SLOTS.items():
            self._equip_slots[slot_id] = (icon, self._t(key, default))

        custom_slots = self._item_service.get_custom_slots()
        for slot_id, name in custom_slots.items():
            if slot_id not in self._equip_slots:
                self._equip_slots[slot_id] = ("📦", name)

        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        self.controls.append(
            ft.Text(
                self._t("player.equip.title", "装备栏"),
                size=12,
                color=THEME.text_muted,
            )
        )

        # Horizontal strip uses the wide right column better than a tall stack.
        equip_cells: List[ft.Control] = []
        for nbt_slot in self._slot_order:
            icon, label = self._equip_slots[nbt_slot]
            cell = self._create_slot(nbt_slot, icon, label)
            self._slot_rows[nbt_slot] = cell
            equip_cells.append(cell)
        self.controls.append(
            ft.Row(
                equip_cells,
                spacing=10,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
                scroll=ft.ScrollMode.AUTO,
            )
        )

    def _create_slot(
        self,
        nbt_slot: int,
        slot_icon_emoji: str,
        label: str,
    ) -> ft.Column:
        slot = create_item_slot(self._slot_size, count_size=10)
        slot_container = slot.container

        slot_icon = ft.Text(slot_icon_emoji, size=14, color=THEME.text_muted)
        label_text = ft.Text(
            label,
            size=11,
            color=THEME.text_secondary,
            text_align=ft.TextAlign.CENTER,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        self._slot_containers[nbt_slot] = slot_container
        self._slot_controls[nbt_slot] = slot

        return ft.Column(
            [
                slot_icon,
                slot_container,
                label_text,
            ],
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            width=max(self._slot_size + 8, 56),
        )

    def set_equipment(self, inventory: List[Dict[str, Any]]) -> None:
        """Fill equipment slots from inventory or equipment-only item list."""
        self._texture_generation += 1
        for nbt_slot in self._slot_order:
            if nbt_slot in self._slot_controls:
                reset_item_slot(self._slot_controls[nbt_slot])

        item_ids_to_load: Dict[int, str] = {}
        equip_slots_set = set(self._equip_slots.keys())

        try:
            for item in inventory:
                si = item.get("slot", -999)
                if si not in equip_slots_set:
                    continue
                if si not in self._slot_controls:
                    continue

                item_info = self._item_service.parse_item(item)
                apply_item_to_slot(
                    self._slot_controls[si],
                    item_info,
                    self._item_service.format_item_tooltip(item_info),
                )
                if item_info.id:
                    item_ids_to_load[si] = item_info.id
        except (TypeError, ValueError, AttributeError, KeyError):
            pass

        safe_update(self)
        self._slot_item_ids = dict(item_ids_to_load)
        if item_ids_to_load:
            self._load_textures_async(item_ids_to_load, self._texture_generation)

    def _load_textures_async(
        self,
        slot_item_map: Dict[int, str],
        generation: int,
    ) -> None:
        def _on_loaded(item_id: str, uri: Optional[str]) -> None:
            if uri is None:
                return

            def apply_loaded() -> None:
                if generation != self._texture_generation:
                    return
                for slot_idx, iid in slot_item_map.items():
                    if (
                        iid == item_id
                        and self._slot_item_ids.get(slot_idx) == item_id
                    ):
                        slot = self._slot_controls.get(slot_idx)
                        if slot is not None:
                            apply_texture_to_slot(slot, uri)

            try:
                page = cast(Optional[ft.Page], self.page)
            except RuntimeError:
                page = None
            run_on_ui(page, apply_loaded)

        unique_ids = list(set(slot_item_map.values()))
        self._texture_service.load_textures_async(
            unique_ids, on_loaded=_on_loaded
        )

    def add_custom_slot(self, slot_id: int, icon: str, label: str) -> None:
        if slot_id in self._equip_slots:
            return

        self._equip_slots[slot_id] = (icon, label)
        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        cell = self._create_slot(slot_id, icon, label)
        self._slot_rows[slot_id] = cell

        title = self.controls[0] if self.controls else ft.Text(
            self._t("player.equip.title", "装备栏"),
            size=12,
            color=THEME.text_muted,
        )
        equip_cells = [self._slot_rows[slot] for slot in self._slot_order]
        self.controls = [
            title,
            ft.Row(
                equip_cells,
                spacing=10,
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
                scroll=ft.ScrollMode.AUTO,
            ),
        ]
        safe_update(self)

    def clear(self) -> None:
        self.set_equipment([])
