"""Shared Minecraft item slot rendering helpers."""
from dataclasses import dataclass

import flet as ft

from app.services.item_icons import get_item_emoji
from app.services.item_service import ItemInfo
from app.ui.views.explorer.utils import safe_update


SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
SLOT_BG_EMPTY = "#2a2a2e"
SLOT_BG_FILLED = "#3a3a3e"

DURABILITY_HIGH = "#4CAF50"
DURABILITY_MEDIUM = "#FF9800"
DURABILITY_LOW = "#F44336"
ENCHANTMENT_COLOR = "#7B68EE"


@dataclass
class ItemSlotControl:
    """Controls that make up a single item slot."""

    container: ft.Container
    image: ft.Image
    icon: ft.Text
    count_text: ft.Text
    durability_text: ft.Text
    enchantment_text: ft.Text


def make_slot_border() -> ft.Border:
    return ft.Border(
        left=ft.BorderSide(2, SLOT_BORDER_LIGHT),
        top=ft.BorderSide(2, SLOT_BORDER_LIGHT),
        right=ft.BorderSide(2, SLOT_BORDER_DARK),
        bottom=ft.BorderSide(2, SLOT_BORDER_DARK),
    )


def create_item_slot(slot_size: int, count_size: int = 9) -> ItemSlotControl:
    image, icon, count_text, durability_text, enchantment_text = (
        _create_slot_layers(slot_size, count_size)
    )
    stack = ft.Stack(
        [
            _overlay_layer(image, slot_size, ft.alignment.Alignment(0, 0)),
            _overlay_layer(icon, slot_size, ft.alignment.Alignment(0, 0)),
            _overlay_layer(
                count_text,
                slot_size,
                ft.alignment.Alignment(1, 1),
                padding=ft.Padding(0, 0, 2, 0),
            ),
            _overlay_layer(
                enchantment_text,
                slot_size,
                ft.alignment.Alignment(-1, -1),
                padding=ft.Padding(2, 0, 0, 0),
            ),
            _overlay_layer(
                durability_text,
                slot_size,
                ft.alignment.Alignment(0, 1),
                padding=ft.Padding(0, 0, 0, 1),
            ),
        ],
        width=slot_size,
        height=slot_size,
    )
    container = ft.Container(
        width=slot_size,
        height=slot_size,
        bgcolor=SLOT_BG_EMPTY,
        border=make_slot_border(),
        border_radius=2,
        padding=0,
        content=stack,
    )
    return ItemSlotControl(
        container,
        image,
        icon,
        count_text,
        durability_text,
        enchantment_text,
    )


def _create_slot_layers(
    slot_size: int,
    count_size: int,
) -> tuple[ft.Image, ft.Text, ft.Text, ft.Text, ft.Text]:
    img_size = int(slot_size * 0.7)
    image = ft.Image(
        src="",
        width=img_size,
        height=img_size,
        fit=ft.BoxFit.CONTAIN,
        visible=False,
    )
    icon = ft.Text("", size=24, text_align=ft.TextAlign.CENTER, visible=True)
    count_text = ft.Text(
        "",
        size=count_size,
        color="#ddd",
        text_align=ft.TextAlign.RIGHT,
        weight=ft.FontWeight.BOLD,
    )
    durability_text = ft.Text(
        "",
        size=6,
        color=DURABILITY_HIGH,
        text_align=ft.TextAlign.CENTER,
    )
    enchantment_text = ft.Text(
        "",
        size=7,
        color=ENCHANTMENT_COLOR,
        text_align=ft.TextAlign.LEFT,
    )
    return image, icon, count_text, durability_text, enchantment_text


def _overlay_layer(
    content: ft.Control,
    slot_size: int,
    alignment: ft.Alignment,
    *,
    padding: ft.Padding | None = None,
) -> ft.Container:
    return ft.Container(
        content=content,
        alignment=alignment,
        padding=padding,
        width=slot_size,
        height=slot_size,
    )


def reset_item_slot(slot: ItemSlotControl) -> None:
    slot.container.bgcolor = SLOT_BG_EMPTY
    slot.container.tooltip = None
    slot.image.visible = False
    slot.image.src = ""
    slot.icon.value = ""
    slot.icon.visible = True
    slot.count_text.value = ""
    slot.durability_text.value = ""
    slot.enchantment_text.value = ""


def apply_item_to_slot(
        slot: ItemSlotControl,
        item_info: ItemInfo,
        tooltip: str) -> None:
    slot.container.bgcolor = SLOT_BG_FILLED
    slot.container.tooltip = tooltip
    slot.icon.value = get_item_emoji(item_info.id)
    slot.icon.visible = True
    slot.count_text.value = f"×{
        item_info.count}" if item_info.count > 1 else ""

    if item_info.durability_percent is not None:
        percent = item_info.durability_percent
        if percent > 60:
            color = DURABILITY_HIGH
        elif percent > 30:
            color = DURABILITY_MEDIUM
        else:
            color = DURABILITY_LOW
        bar_len = 6
        filled = int(percent / 100 * bar_len)
        slot.durability_text.value = "█" * filled + "░" * (bar_len - filled)
        slot.durability_text.color = color

    if item_info.enchantments:
        slot.enchantment_text.value = "✦" * min(len(item_info.enchantments), 3)
        slot.enchantment_text.color = ENCHANTMENT_COLOR


def apply_texture_to_slot(slot: ItemSlotControl, uri: str) -> None:
    slot.image.src = uri
    slot.image.visible = True
    slot.icon.visible = False
    safe_update(slot.image)
    safe_update(slot.icon)
