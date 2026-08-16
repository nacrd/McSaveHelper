"""Qt 物品栏网格：主背包 / 末影箱 / 潜影盒，支持异步贴图。"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.qtui.utils import run_on_ui
from app.qtui.views.item_slot import QtItemSlot
from app.services.item_service import ItemService
from app.services.texture_service import TextureService


Translate = Callable[..., str]
SlotClickCallback = Callable[[int, Optional[dict[str, Any]]], None]


class QtInventoryGrid(QWidget):
    """可配置物品栏网格。

    贴图异步加载用 generation 丢弃过期回调，避免切玩家后串图。
    """

    def __init__(
        self,
        item_service: ItemService,
        texture_service: TextureService | None = None,
        slot_size: int = 44,
        *,
        layout: str = "main",
        translate: Optional[Translate] = None,
        on_slot_click: Optional[SlotClickCallback] = None,
        title: Optional[str] = None,
    ) -> None:
        """构建主背包/末影箱/潜影盒网格。"""
        super().__init__()
        self._slot_size = slot_size
        self._item_service = item_service
        self._texture_service = texture_service
        self._texture_generation = 0
        self._disposed = False
        self._slots: dict[int, QtItemSlot] = {}
        self._slot_item_ids: dict[int, str] = {}
        self._slot_items: dict[int, dict[str, Any]] = {}
        self._selected_slot: Optional[int] = None
        self._layout_name = layout
        self._on_slot_click = on_slot_click
        self._t = translate or (lambda key, default="", **_kw: default or key)
        self._custom_title = title
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        if layout == "ender":
            self._build_grid_rows(
                root,
                range(0, 27),
                self._custom_title
                or self._t("player.inventory.ender", "末影箱"),
            )
        elif layout == "shulker":
            self._build_grid_rows(
                root,
                range(0, 27),
                self._custom_title
                or self._t("player.inventory.shulker", "潜影盒内容"),
            )
        else:
            self._build_main_layout(root)
        root.addStretch(1)

    def set_on_slot_click(self, callback: Optional[SlotClickCallback]) -> None:
        """设置或清除槽点击回调。"""
        self._on_slot_click = callback

    def set_inventory(
        self,
        inventory: Sequence[Mapping[str, Any]],
        *,
        selected_slot: Optional[int] = None,
    ) -> None:
        """用物品列表填充格子并异步加载贴图。"""
        if self._disposed:
            return
        self._texture_generation += 1
        self._selected_slot = selected_slot
        self._slot_items = {}
        for nbt_slot, slot in self._slots.items():
            slot.reset()
            del nbt_slot

        item_ids_to_load: dict[int, str] = {}
        allowed = set(self._slots.keys())
        try:
            for item in inventory:
                raw_slot = item.get("slot", -1)
                try:
                    si = int(raw_slot)
                except (TypeError, ValueError):
                    continue
                if si not in allowed:
                    continue
                slot = self._slots[si]
                payload = dict(item)
                self._slot_items[si] = payload
                item_info = self._item_service.parse_item(payload)
                tooltip = self._item_service.format_item_tooltip(item_info)
                if self._on_slot_click is not None:
                    tooltip = (
                        f"{tooltip}\n"
                        f"{self._t('player.inventory.click_hint', '点击查看详情')}"
                    )
                slot.apply_item(item_info, tooltip)
                if item_info.id:
                    item_ids_to_load[si] = item_info.id
        except (TypeError, ValueError, AttributeError, KeyError):
            pass

        if (
            self._layout_name == "main"
            and selected_slot is not None
            and selected_slot in self._slots
        ):
            self._slots[selected_slot].set_selected(True)

        self._slot_item_ids = dict(item_ids_to_load)
        if item_ids_to_load and self._texture_service is not None:
            self._load_textures_async(item_ids_to_load, self._texture_generation)

    def set_selected_slot(self, selected_slot: Optional[int]) -> None:
        """仅更新主背包快捷栏高亮。"""
        if self._layout_name != "main":
            return
        previous = self._selected_slot
        self._selected_slot = selected_slot
        if previous is not None and previous in self._slots:
            self._slots[previous].set_selected(False)
        if selected_slot is not None and selected_slot in self._slots:
            self._slots[selected_slot].set_selected(True)

    def set_title(self, title: str) -> None:
        """更新网格标题（潜影盒预览用）。"""
        if hasattr(self, "_title_label"):
            self._title_label.setText(title)

    def clear(self) -> None:
        """清空所有格子。"""
        self.set_inventory([])

    def dispose(self) -> None:
        """使进行中的贴图回调失效；可重复调用。"""
        if self._disposed:
            return
        self._disposed = True
        self._texture_generation += 1
        self._slot_item_ids.clear()
        self._slot_items.clear()

    def slot_item(self, nbt_slot: int) -> Optional[dict[str, Any]]:
        """返回指定槽当前物品字典（测试用）。"""
        return self._slot_items.get(nbt_slot)

    def _build_main_layout(self, root: QVBoxLayout) -> None:
        self._title_label = QLabel(
            self._custom_title
            or self._t("player.inventory.main", "主物品栏")
        )
        self._title_label.setProperty("role", "muted")
        root.addWidget(self._title_label)
        for row in range(3):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(2)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            for col in range(9):
                row_layout.addWidget(self._make_slot(9 + row * 9 + col))
            row_layout.addStretch(1)
            root.addLayout(row_layout)
        hotbar_title = QLabel(self._t("player.inventory.hotbar", "快捷栏"))
        hotbar_title.setProperty("role", "muted")
        root.addWidget(hotbar_title)
        hotbar = QHBoxLayout()
        hotbar.setSpacing(2)
        hotbar.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for col in range(9):
            hotbar.addWidget(self._make_slot(col))
        hotbar.addStretch(1)
        root.addLayout(hotbar)

    def _build_grid_rows(
        self,
        root: QVBoxLayout,
        slots: range,
        title: str,
    ) -> None:
        self._title_label = QLabel(title)
        self._title_label.setProperty("role", "muted")
        root.addWidget(self._title_label)
        slot_list = list(slots)
        for row_start in range(0, len(slot_list), 9):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(2)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            for si in slot_list[row_start:row_start + 9]:
                row_layout.addWidget(self._make_slot(si))
            row_layout.addStretch(1)
            root.addLayout(row_layout)

    def _make_slot(self, nbt_slot: int) -> QtItemSlot:
        slot = QtItemSlot(
            self._slot_size,
            on_click=lambda s=nbt_slot: self._handle_slot_click(s),
        )
        self._slots[nbt_slot] = slot
        return slot

    def _handle_slot_click(self, nbt_slot: int) -> None:
        if self._on_slot_click is None:
            return
        self._on_slot_click(nbt_slot, self._slot_items.get(nbt_slot))

    def _load_textures_async(
        self,
        slot_item_map: dict[int, str],
        generation: int,
    ) -> None:
        texture = self._texture_service
        if texture is None:
            return

        def on_loaded(item_id: str, uri: Optional[str]) -> None:
            if uri is None:
                return

            def apply_loaded() -> None:
                if self._disposed or generation != self._texture_generation:
                    return
                for slot_idx, iid in slot_item_map.items():
                    if (
                        iid == item_id
                        and self._slot_item_ids.get(slot_idx) == item_id
                    ):
                        slot = self._slots.get(slot_idx)
                        if slot is not None:
                            slot.apply_texture(uri)

            run_on_ui(apply_loaded)

        unique_ids = list(set(slot_item_map.values()))
        texture.load_textures_async(unique_ids, on_loaded=on_loaded)


__all__ = ["QtInventoryGrid"]
