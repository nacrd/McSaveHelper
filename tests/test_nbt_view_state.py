from pathlib import Path

from app.models.nbt_edit import ChunkNbtTarget
from app.presenters.nbt_view_state import (
    NbtViewState,
    clear_chunk_target,
    clear_nbt_target,
    set_nbt_target,
    toggle_left_panel,
    toggle_right_panel,
)


def test_nbt_target_transition_keeps_one_coherent_snapshot() -> None:
    chunk = ChunkNbtTarget(Path("r.0.0.mca"), 1, 2, {"DataVersion": 1})

    selected = set_nbt_target(
        NbtViewState(),
        chunk,
        "区块 NBT",
        "chunk",
        chunk,
    )

    assert selected.target is chunk
    assert selected.chunk_target is chunk
    assert selected.label == "区块 NBT"
    assert clear_chunk_target(selected).chunk_target is None


def test_nbt_reset_preserves_panel_preferences() -> None:
    collapsed = toggle_right_panel(toggle_left_panel(NbtViewState()))

    reset = clear_nbt_target(collapsed)

    assert reset.target is None
    assert reset.label == "未加载 NBT"
    assert reset.edit_format == "nbt"
    assert reset.is_left_collapsed is True
    assert reset.is_right_collapsed is True
