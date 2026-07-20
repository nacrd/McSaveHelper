"""Inventory Grid component - Minecraft style slots with texture support."""
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
    make_slot_border,
    reset_item_slot,
)
from app.ui.views.explorer.utils import safe_update

Translate = Callable[..., str]

# Highlight for SelectedItemSlot
SELECTED_BORDER = "#42A5F5"


class InventoryGrid(ft.Column):
    """Configurable inventory grid (main inventory or ender chest)."""

    def __init__(
        self,
        item_service: ItemService,
        texture_service: TextureService,
        slot_size: int = 48,
        *,
        layout: str = "main",
        t_cb: Optional[Translate] = None,
    ) -> None:
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._slot_controls: Dict[int, ItemSlotControl] = {}
        self._item_service = item_service
        self._texture_service = texture_service
        self._texture_generation = 0
        self._slot_item_ids: Dict[int, str] = {}
        self._t = t_cb or (lambda key, default="", **_kw: default or key)
        self._layout = layout
        self._selected_slot: Optional[int] = None
        self._title_main: Optional[ft.Text] = None
        self._title_hotbar: Optional[ft.Text] = None
        self._title_ender: Optional[ft.Text] = None

        if layout == "ender":
            self._build_ender_layout()
        else:
            self._build_main_layout()

    def _make_slot(self, nbt_slot: int) -> ft.Container:
        slot = create_item_slot(self._slot_size)
        self._slots[nbt_slot] = slot.container
        self._slot_controls[nbt_slot] = slot
        return slot.container

    def _build_main_layout(self) -> None:
        main_rows: List[ft.Control] = []
        for row in range(3):
            slots_row: List[ft.Control] = [
                self._make_slot(9 + row * 9 + col) for col in range(9)
            ]
            main_rows.append(
                ft.Row(
                    slots_row,
                    spacing=2,
                    alignment=ft.MainAxisAlignment.START,
                )
            )

        hotbar_slots: List[ft.Control] = [
            self._make_slot(col) for col in range(9)
        ]
        hotbar_row = ft.Row(
            hotbar_slots,
            spacing=2,
            alignment=ft.MainAxisAlignment.START,
        )

        self._title_main = ft.Text(
            self._t("player.inventory.main", "主物品栏"),
            size=12,
            color=THEME.text_muted,
        )
        self._title_hotbar = ft.Text(
            self._t("player.inventory.hotbar", "快捷栏"),
            size=12,
            color=THEME.text_muted,
        )
        self.controls = [
            self._title_main,
            *main_rows,
            ft.Container(height=8),
            self._title_hotbar,
            hotbar_row,
        ]

    def _build_ender_layout(self) -> None:
        rows: List[ft.Control] = []
        for row in range(3):
            slots_row: List[ft.Control] = [
                self._make_slot(row * 9 + col) for col in range(9)
            ]
            rows.append(
                ft.Row(
                    slots_row,
                    spacing=2,
                    alignment=ft.MainAxisAlignment.START,
                )
            )
        self._title_ender = ft.Text(
            self._t("player.inventory.ender", "末影箱"),
            size=12,
            color=THEME.text_muted,
        )
        self.controls = [self._title_ender, *rows]

    def set_inventory(
        self,
        inventory: List[Dict[str, Any]],
        *,
        selected_slot: Optional[int] = None,
    ) -> None:
        self._texture_generation += 1
        self._selected_slot = selected_slot
        for nbt_slot in self._slots:
            reset_item_slot(self._slot_controls[nbt_slot])
            self._apply_slot_highlight(nbt_slot, selected=False)

        item_ids_to_load: Dict[int, str] = {}
        allowed = set(self._slots.keys())

        try:
            for item in inventory:
                si = item.get("slot", -1)
                if si not in allowed:
                    continue
                slot_ctrl = self._slot_controls.get(si)
                if slot_ctrl is None:
                    continue

                item_info = self._item_service.parse_item(item)
                apply_item_to_slot(
                    slot_ctrl,
                    item_info,
                    self._item_service.format_item_tooltip(item_info),
                )
                if item_info.id:
                    item_ids_to_load[si] = item_info.id
        except (TypeError, ValueError, AttributeError, KeyError):
            pass

        if (
            self._layout == "main"
            and selected_slot is not None
            and selected_slot in self._slots
        ):
            self._apply_slot_highlight(selected_slot, selected=True)

        safe_update(self)
        self._slot_item_ids = dict(item_ids_to_load)
        if item_ids_to_load:
            self._load_textures_async(item_ids_to_load, self._texture_generation)

    def set_selected_slot(self, selected_slot: Optional[int]) -> None:
        """Update hotbar selection highlight without reloading items."""
        if self._layout != "main":
            return
        previous = self._selected_slot
        self._selected_slot = selected_slot
        if previous is not None and previous in self._slots:
            self._apply_slot_highlight(previous, selected=False)
        if selected_slot is not None and selected_slot in self._slots:
            self._apply_slot_highlight(selected_slot, selected=True)
        safe_update(self)

    def _apply_slot_highlight(self, nbt_slot: int, *, selected: bool) -> None:
        container = self._slots.get(nbt_slot)
        if container is None:
            return
        if selected:
            container.border = ft.Border.all(2, SELECTED_BORDER)
        else:
            container.border = make_slot_border()

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

    def clear(self) -> None:
        self.set_inventory([])
