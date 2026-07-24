"""Explorer NBT 页签的不可变视图状态。"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtEditFormat,
    NbtTarget,
)


@dataclass(frozen=True)
class NbtViewState:
    """当前 NBT 目标和面板投影快照。"""

    target: NbtTarget | None = None
    label: str = "未加载 NBT"
    edit_format: NbtEditFormat = "nbt"
    chunk_target: ChunkNbtTarget | None = None
    is_left_collapsed: bool = False
    is_right_collapsed: bool = False


def set_nbt_view(
    state: NbtViewState,
    label: str,
    edit_format: NbtEditFormat,
) -> NbtViewState:
    """Update the visible label and format without changing its target."""
    return replace(state, label=label, edit_format=edit_format)


def set_nbt_target(
    state: NbtViewState,
    target: NbtTarget | None,
    label: str,
    edit_format: NbtEditFormat,
    chunk_target: ChunkNbtTarget | None,
) -> NbtViewState:
    """Replace the complete current NBT target projection."""
    return replace(
        state,
        target=target,
        label=label,
        edit_format=edit_format,
        chunk_target=chunk_target,
    )


def clear_nbt_target(state: NbtViewState) -> NbtViewState:
    """Reset target state while preserving panel preferences."""
    return replace(
        state,
        target=None,
        label="未加载 NBT",
        edit_format="nbt",
        chunk_target=None,
    )


def clear_chunk_target(state: NbtViewState) -> NbtViewState:
    """Detach a previous chunk before loading a non-chunk target."""
    return replace(state, chunk_target=None)


def toggle_left_panel(state: NbtViewState) -> NbtViewState:
    """Toggle the navigation panel projection."""
    return replace(state, is_left_collapsed=not state.is_left_collapsed)


def toggle_right_panel(state: NbtViewState) -> NbtViewState:
    """Toggle the staged-change panel projection."""
    return replace(state, is_right_collapsed=not state.is_right_collapsed)


__all__ = [
    "NbtViewState",
    "clear_chunk_target",
    "clear_nbt_target",
    "set_nbt_target",
    "set_nbt_view",
    "toggle_left_panel",
    "toggle_right_panel",
]
