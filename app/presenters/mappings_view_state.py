"""映射页面异步交互的不可变状态。"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class MappingsViewState:
    """映射页操作占用与生命周期快照。"""

    item_busy: bool = False
    is_disposed: bool = False

    @property
    def can_edit_items(self) -> bool:
        """Return whether item mapping controls may start work."""
        return not self.item_busy and not self.is_disposed


def set_item_busy(state: MappingsViewState, busy: bool) -> MappingsViewState:
    """Update item-operation ownership while preserving disposal state."""
    if state.is_disposed and busy:
        return state
    return replace(state, item_busy=busy)


def dispose_mappings_state(state: MappingsViewState) -> MappingsViewState:
    """Invalidate all later mapping callbacks and release local busy state."""
    return replace(state, item_busy=False, is_disposed=True)


__all__ = [
    "MappingsViewState",
    "dispose_mappings_state",
    "set_item_busy",
]
