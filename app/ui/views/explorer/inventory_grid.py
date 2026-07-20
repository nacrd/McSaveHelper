"""物品栏网格：Minecraft 风格槽位，支持贴图异步加载。"""
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
SlotClickCallback = Callable[[int, Optional[Dict[str, Any]]], None]

# Highlight for SelectedItemSlot
SELECTED_BORDER = "#42A5F5"


class InventoryGrid(ft.Column):
    """可配置物品栏网格（主背包 / 末影箱 / 潜影盒）。

    贴图异步加载用 generation 丢弃过期回调，避免切玩家后串图。
    """

    def __init__(
        self,
        item_service: ItemService,
        texture_service: TextureService,
        slot_size: int = 48,
        *,
        layout: str = "main",
        t_cb: Optional[Translate] = None,
        on_slot_click: Optional[SlotClickCallback] = None,
        title: Optional[str] = None,
    ) -> None:
        """构建主背包/末影箱/潜影盒网格。

        Args:
            item_service: 物品解析与命名。
            texture_service: 贴图解析。
            slot_size: 槽像素边长。
            layout: ``main`` / ``ender`` / ``shulker``。
            t_cb: 翻译回调。
            on_slot_click: 槽点击 ``(slot_index, item_dict|None)``。
            title: 可选自定义标题。
        """
        super().__init__(spacing=0)
        self._slot_size = slot_size
        self._slots: Dict[int, ft.Container] = {}
        self._slot_controls: Dict[int, ItemSlotControl] = {}
        self._item_service = item_service
        self._texture_service = texture_service
        self._texture_generation = 0
        self._slot_item_ids: Dict[int, str] = {}
        self._slot_items: Dict[int, Dict[str, Any]] = {}
        self._t = t_cb or (lambda key, default="", **_kw: default or key)
        self._layout = layout
        self._on_slot_click = on_slot_click
        self._selected_slot: Optional[int] = None
        self._custom_title = title
        self._title_main: Optional[ft.Text] = None
        self._title_hotbar: Optional[ft.Text] = None
        self._title_ender: Optional[ft.Text] = None

        if layout == "ender":
            self._build_ender_layout()
        elif layout == "shulker":
            self._build_shulker_layout()
        else:
            self._build_main_layout()

    def set_on_slot_click(self, callback: Optional[SlotClickCallback]) -> None:
        """设置或清除槽点击回调。"""
        self._on_slot_click = callback

    def _make_slot(self, nbt_slot: int) -> ft.Container:
        slot = create_item_slot(self._slot_size)
        container = slot.container
        container.data = nbt_slot
        container.on_click = lambda e, s=nbt_slot: self._handle_slot_click(s)
        self._slots[nbt_slot] = container
        self._slot_controls[nbt_slot] = slot
        return container

    def _handle_slot_click(self, nbt_slot: int) -> None:
        if self._on_slot_click is None:
            return
        item = self._slot_items.get(nbt_slot)
        self._on_slot_click(nbt_slot, item)

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
            self._custom_title
            or self._t("player.inventory.main", "主物品栏"),
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
        self.controls = self._build_grid_rows(
            slots=range(0, 27),
            title=self._custom_title
            or self._t("player.inventory.ender", "末影箱"),
        )

    def _build_shulker_layout(self) -> None:
        self.controls = self._build_grid_rows(
            slots=range(0, 27),
            title=self._custom_title
            or self._t("player.inventory.shulker", "潜影盒内容"),
        )

    def _build_grid_rows(
        self,
        slots: range,
        title: str,
    ) -> List[ft.Control]:
        slot_list = list(slots)
        rows: List[ft.Control] = []
        for row_start in range(0, len(slot_list), 9):
            row_slots = slot_list[row_start:row_start + 9]
            rows.append(
                ft.Row(
                    [self._make_slot(si) for si in row_slots],
                    spacing=2,
                    alignment=ft.MainAxisAlignment.START,
                )
            )
        title_ctrl = ft.Text(title, size=12, color=THEME.text_muted)
        self._title_ender = title_ctrl
        return [title_ctrl, *rows]

    def set_inventory(
        self,
        inventory: List[Dict[str, Any]],
        *,
        selected_slot: Optional[int] = None,
    ) -> None:
        """用物品列表填充格子并异步加载贴图。

        仅接受本布局已创建的 NBT slot 编号；未知 slot 忽略。

        Args:
            inventory: 含 ``slot`` 字段的物品字典列表。
            selected_slot: 主背包可选高亮 slot（快捷栏选择）。
        """
        self._texture_generation += 1
        self._selected_slot = selected_slot
        self._slot_items = {}
        for nbt_slot in self._slots:
            reset_item_slot(self._slot_controls[nbt_slot])
            self._apply_slot_highlight(nbt_slot, selected=False)
            container = self._slots[nbt_slot]
            container.on_click = (
                lambda e, s=nbt_slot: self._handle_slot_click(s)
            )

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

                self._slot_items[si] = item
                item_info = self._item_service.parse_item(item)
                tooltip = self._item_service.format_item_tooltip(item_info)
                if self._on_slot_click is not None:
                    tooltip = (
                        f"{tooltip}\n"
                        f"{self._t('player.inventory.click_hint', '点击查看详情')}"
                    )
                apply_item_to_slot(slot_ctrl, item_info, tooltip)
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
        """仅更新主背包快捷栏高亮，不重载物品。

        Args:
            selected_slot: 要高亮的 NBT slot；None 清除高亮。
        """
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
        """清空所有格子（等价于空物品栏）。"""
        self.set_inventory([])
