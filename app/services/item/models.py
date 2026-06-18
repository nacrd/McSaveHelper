"""Item service models."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ItemInfo:
    """物品信息"""
    id: str
    display_name: str
    count: int = 1
    damage: Optional[int] = None
    max_damage: Optional[int] = None
    durability_percent: Optional[float] = None
    enchantments: List[Dict[str, Any]] = None
    custom_name: Optional[str] = None
    lore: List[str] = None
    slot: int = -1

    def __post_init__(self):
        if self.enchantments is None:
            self.enchantments = []
        if self.lore is None:
            self.lore = []
