"""Qt 装备预览：盔甲 + 副手槽，支持异步贴图。"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.qtui.utils import run_on_ui
from app.qtui.views.item_slot import QtItemSlot, QtLabeledSlot
from app.services.item_service import ItemService
from app.services.texture_service import TextureService


Translate = Callable[..., str]


class QtEquipmentPreview(QWidget):
    """玩家装备预览条。"""

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
        texture_service: TextureService | None = None,
        slot_size: int = 44,
        *,
        translate: Optional[Translate] = None,
    ) -> None:
        """构建装备条。"""
        super().__init__()
        self._slot_size = slot_size
        self._item_service = item_service
        self._texture_service = texture_service
        self._texture_generation = 0
        self._disposed = False
        self._slot_controls: dict[int, QtItemSlot] = {}
        self._slot_item_ids: dict[int, str] = {}
        self._t = translate or (lambda key, default="", **_kw: default or key)

        self._equip_slots: dict[int, tuple[str, str]] = {}
        for slot_id, (icon, key, default) in self.DEFAULT_EQUIP_SLOTS.items():
            self._equip_slots[slot_id] = (icon, self._t(key, default))
        for slot_id, name in self._item_service.get_custom_slots().items():
            if slot_id not in self._equip_slots:
                self._equip_slots[slot_id] = ("📦", name)
        self._slot_order = sorted(self._equip_slots.keys(), reverse=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel(self._t("player.equip.title", "装备栏"))
        title.setProperty("role", "muted")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        strip_host = QWidget()
        strip = QHBoxLayout(strip_host)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(8)
        strip.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cell_width = max(self._slot_size + 8, 56)
        for nbt_slot in self._slot_order:
            icon, label = self._equip_slots[nbt_slot]
            slot = QtItemSlot(self._slot_size, count_size=10)
            self._slot_controls[nbt_slot] = slot
            strip.addWidget(QtLabeledSlot(icon, label, slot, cell_width))
        strip.addStretch(1)
        scroll.setWidget(strip_host)
        scroll.setFixedHeight(self._slot_size + 42)
        root.addWidget(scroll)

    def set_equipment(self, inventory: Sequence[Mapping[str, Any]]) -> None:
        """用物品列表填充装备槽并异步加载贴图。"""
        if self._disposed:
            return
        self._texture_generation += 1
        for slot in self._slot_controls.values():
            slot.reset()

        item_ids_to_load: dict[int, str] = {}
        equip_slots = set(self._equip_slots.keys())
        try:
            for item in inventory:
                raw_slot = item.get("slot", -999)
                try:
                    si = int(raw_slot)
                except (TypeError, ValueError):
                    continue
                if si not in equip_slots or si not in self._slot_controls:
                    continue
                payload = dict(item)
                item_info = self._item_service.parse_item(payload)
                self._slot_controls[si].apply_item(
                    item_info,
                    self._item_service.format_item_tooltip(item_info),
                )
                if item_info.id:
                    item_ids_to_load[si] = item_info.id
        except (TypeError, ValueError, AttributeError, KeyError):
            pass

        self._slot_item_ids = dict(item_ids_to_load)
        if item_ids_to_load and self._texture_service is not None:
            self._load_textures_async(item_ids_to_load, self._texture_generation)

    def clear(self) -> None:
        """清空装备槽。"""
        self.set_equipment([])

    def dispose(self) -> None:
        """使贴图回调失效。"""
        if self._disposed:
            return
        self._disposed = True
        self._texture_generation += 1
        self._slot_item_ids.clear()

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
                        slot = self._slot_controls.get(slot_idx)
                        if slot is not None:
                            slot.apply_texture(uri)

            run_on_ui(apply_loaded)

        texture.load_textures_async(
            list(set(slot_item_map.values())),
            on_loaded=on_loaded,
        )


__all__ = ["QtEquipmentPreview"]
