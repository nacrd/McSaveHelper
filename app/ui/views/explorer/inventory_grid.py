"""Inventory Grid component - Minecraft 风格物品栏，支持纹理图片"""
import flet as ft
from typing import Any, Dict, List, Optional

from app.ui.theme import THEME
from app.ui.views.explorer.utils import safe_update
from app.services.item_service import get_item_service, ItemInfo
from app.services.texture_service import get_texture_service
from app.services.item_icons import get_item_emoji


class InventoryGrid(ft.Column):
    """Minecraft 原版物品栏布局：3×9 主物品栏 + 间隔 + 1×9 快捷栏"""

    SLOT_BORDER_LIGHT = "rgba(255,255,255,0.08)"
    SLOT_BORDER_DARK = "rgba(0,0,0,0.45)"
    SLOT_BG_EMPTY = "#2a2a2e"
    SLOT_BG_FILLED = "#3a3a3e"

    DURABILITY_HIGH = "#4CAF50"
    DURABILITY_MEDIUM = "#FF9800"
    DURABILITY_LOW = "#F44336"
    ENCHANTMENT_COLOR = "#7B68EE"

    def __init__(self, slot_size: int = 48) -> None:
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._img_size = int(slot_size * 0.7)
        self._slots: Dict[int, ft.Container] = {}
        self._slot_stacks: Dict[int, ft.Stack] = {}
        self._slot_images: Dict[int, ft.Image] = {}
        self._slot_icons: Dict[int, ft.Text] = {}
        self._slot_count_texts: Dict[int, ft.Text] = {}
        self._slot_dur_texts: Dict[int, ft.Text] = {}
        self._slot_ench_texts: Dict[int, ft.Text] = {}
        self._item_service = get_item_service()
        self._texture_service = get_texture_service()

        def make_slot_border():
            return ft.Border(
                left=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                top=ft.BorderSide(2, self.SLOT_BORDER_LIGHT),
                right=ft.BorderSide(2, self.SLOT_BORDER_DARK),
                bottom=ft.BorderSide(2, self.SLOT_BORDER_DARK),
            )

        def make_slot(nbt_slot: int) -> ft.Container:
            # 图片（真实纹理）
            img = ft.Image(
                src="",
                width=self._img_size,
                height=self._img_size,
                fit=ft.BoxFit.CONTAIN,
                visible=False,
            )
            # Emoji 图标（回退）
            icon = ft.Text(
                "",
                size=24,
                text_align=ft.TextAlign.CENTER,
                visible=True,
            )
            count_text = ft.Text(
                "", size=9, color="#ddd",
                text_align=ft.TextAlign.RIGHT,
                weight=ft.FontWeight.BOLD,
            )
            dur_text = ft.Text("", size=6, color=self.DURABILITY_HIGH, text_align=ft.TextAlign.CENTER)
            ench_text = ft.Text("", size=7, color=self.ENCHANTMENT_COLOR, text_align=ft.TextAlign.LEFT)

            stack = ft.Stack(
                [
                    # 真实纹理图片
                    ft.Container(
                        content=img,
                        alignment=ft.alignment.Alignment(0, 0),
                        width=slot_size,
                        height=slot_size,
                    ),
                    # Emoji 图标回退
                    ft.Container(
                        content=icon,
                        alignment=ft.alignment.Alignment(0, 0),
                        width=slot_size,
                        height=slot_size,
                    ),
                    ft.Container(
                        content=count_text,
                        alignment=ft.alignment.Alignment(1, 1),
                        padding=ft.Padding(0, 0, 2, 0),
                        width=slot_size,
                        height=slot_size,
                    ),
                    ft.Container(
                        content=ench_text,
                        alignment=ft.alignment.Alignment(-1, -1),
                        padding=ft.Padding(2, 0, 0, 0),
                        width=slot_size,
                        height=slot_size,
                    ),
                    ft.Container(
                        content=dur_text,
                        alignment=ft.alignment.Alignment(0, 1),
                        padding=ft.Padding(0, 0, 0, 1),
                        width=slot_size,
                        height=slot_size,
                    ),
                ],
                width=slot_size,
                height=slot_size,
            )

            s = ft.Container(
                width=slot_size,
                height=slot_size,
                bgcolor=self.SLOT_BG_EMPTY,
                border=make_slot_border(),
                border_radius=2,
                padding=0,
                content=stack,
            )
            self._slots[nbt_slot] = s
            self._slot_stacks[nbt_slot] = stack
            self._slot_images[nbt_slot] = img
            self._slot_icons[nbt_slot] = icon
            self._slot_count_texts[nbt_slot] = count_text
            self._slot_dur_texts[nbt_slot] = dur_text
            self._slot_ench_texts[nbt_slot] = ench_text
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
            s.tooltip = None
            self._slot_images[nbt_slot].visible = False
            self._slot_images[nbt_slot].src = None
            self._slot_icons[nbt_slot].value = ""
            self._slot_icons[nbt_slot].visible = True
            self._slot_count_texts[nbt_slot].value = ""
            self._slot_dur_texts[nbt_slot].value = ""
            self._slot_ench_texts[nbt_slot].value = ""

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
                s.bgcolor = self.SLOT_BG_FILLED
                s.tooltip = self._item_service.format_item_tooltip(item_info)

                icon_text = self._slot_icons[si]
                count_text = self._slot_count_texts[si]
                dur_text = self._slot_dur_texts[si]
                ench_text = self._slot_ench_texts[si]

                # 设置 Emoji 图标作为回退
                icon_text.value = get_item_emoji(item_info.id)
                icon_text.visible = True

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
                    img = self._slot_images.get(slot_idx)
                    icon = self._slot_icons.get(slot_idx)
                    if img is not None and icon is not None:
                        img.src = uri
                        img.visible = True
                        icon.visible = False  # 隐藏 Emoji
                        safe_update(img)
                        safe_update(icon)

        unique_ids = list(set(slot_item_map.values()))
        self._texture_service.load_textures_async(unique_ids, on_loaded=_on_loaded)

    def clear(self) -> None:
        self.set_inventory([])
