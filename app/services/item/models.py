"""Item service models."""
from dataclasses import dataclass, field
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
    enchantments: List[Dict[str, Any]] = field(default_factory=list)
    custom_name: Optional[str] = None
    lore: List[str] = field(default_factory=list)
    slot: int = -1
