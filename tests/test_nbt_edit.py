"""Tests for the typed NBT staging and commit boundary."""
from pathlib import Path
from copy import deepcopy
from types import SimpleNamespace
from typing import Any, cast

import flet as ft

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtChange,
    NbtEditFormat,
    NbtStageStore,
)
from app.services.block_data_service import BlockDataService
from app.ui.views.explorer.nbt.chunk_operations import ChunkOperations
from app.ui.views.explorer.nbt.nbt_data_loader import NbtDataLoader
from app.ui.views.explorer.nbt.nbt_commit_handler import NbtCommitHandler
from app.ui.views.explorer.nbt_tab import NbtTabMixin
from core.omni.world_session import WorldSession


def _change(
    *,
    target: Any = Path("level.dat"),
    format: NbtEditFormat = "nbt",
    old_value: Any = 1,
    new_value: Any = 2,
    path: list[Any] | None = None,
) -> NbtChange:
    return NbtChange.create(
        target=target,
        target_label="测试目标",
        format=format,
        path=path or ["Data", "value"],
        display_path="Data.value",
        old_value=old_value,
        new_value=new_value,
    )


def test_nbt_change_derives_operation_and_freezes_path() -> None:
    path = ["Data", "value"]
    change = NbtChange.create(
        target=Path("level.dat"),
        target_label="level.dat",
        format="nbt",
        path=path,
        display_path="Data.value",
        old_value=None,
        new_value=3,
    )
    path.append("later")

    assert change.operation == "add"
    assert change.path == ("Data", "value")


def test_stage_store_owns_mutation_and_groups_targets() -> None:
    store = NbtStageStore()
    first = _change()
    second = _change(new_value=3)
    player = _change(target="player-uuid")

    store.add(first)
    store.add(second)
    store.add(player)

    assert len(store) == 3
    assert list(store.grouped_by_target()) == ["file:level.dat", "player:player-uuid"]
    assert store.remove(10) is None
    assert store.remove(1) is second
    assert store.changes == (first, player)
    assert store.clear() == 2
    assert not store


class FakeSession(WorldSession):
    def __init__(self, world_path: Path, chunk_data: Any = None) -> None:
        self.world_path = world_path
        self.queued = []
        self.committed_with_backup = False
        self.chunk_data = chunk_data or {"Data": {"value": 1}, "sections": []}

    def queue_modify_nbt(self, target, path, value, operation="set") -> None:
        self.queued.append(("nbt", target, path, value, operation))

    def queue_modify_json(self, target, path, value, operation="set") -> None:
        self.queued.append(("json", target, path, value, operation))

    def queue_modify_chunk(self, region_path, chunk_x, chunk_z, data) -> None:
        self.queued.append(("chunk", region_path, chunk_x, chunk_z, data))

    def load_chunk_nbt(self, region_path, chunk_x, chunk_z):
        return deepcopy(self.chunk_data), region_path

    def get_queue_size(self) -> int:
        return len(self.queued)

    def commit(self, backup: bool = True) -> bool:
        self.committed_with_backup = backup
        return True


def test_commit_handler_queues_typed_changes_and_refreshes_session() -> None:
    store = NbtStageStore()
    chunk_data = {"Data": {"value": 4}, "sections": []}
    chunk_target = ChunkNbtTarget(Path("region/r.0.0.mca"), 1, 2, chunk_data)
    store.add(_change())
    store.add(_change(target=Path("stats/test.json"), format="json"))
    store.add(_change(target=chunk_target, format="chunk"))
    # Multiple edits to one chunk must still queue one complete chunk write.
    store.add(_change(target=chunk_target, format="chunk", new_value=4))

    session = FakeSession(Path("world"))
    replacements = []
    refreshed = []
    messages = []

    handler = NbtCommitHandler(
        store=store,
        get_world_session=lambda: session,
        replace_world_session=replacements.append,
        get_page=lambda: None,
        refresh_stage=lambda: refreshed.append("stage"),
        reload_current_target=lambda: refreshed.append("target"),
        warn=lambda title, message: messages.append((title, message)),
        info=lambda title, message: messages.append((title, message)),
        error=lambda title, message: messages.append((title, message)),
        handle_error=lambda error, title: messages.append((title, str(error))),
        log=lambda message, level: None,
        session_factory=lambda path, log: FakeSession(path),
    )

    handler.execute_commit()

    assert [queued[0] for queued in session.queued] == ["nbt", "json", "chunk"]
    assert session.committed_with_backup is True
    assert not store
    assert refreshed == ["stage", "target"]
    assert len(replacements) == 1
    assert messages[-1][0] == "提交完成"


def test_chunk_commit_replays_only_remaining_changes_from_disk() -> None:
    store = NbtStageStore()
    mutable_data = {"Data": {"kept": 2, "removed": 1}}
    target = ChunkNbtTarget(Path("region/r.0.0.mca"), 0, 0, mutable_data)
    removed = _change(
        target=target,
        format="chunk",
        old_value=0,
        new_value=1,
        path=["Data", "removed"],
    )
    kept = _change(
        target=target,
        format="chunk",
        old_value=0,
        new_value=2,
        path=["Data", "kept"],
    )
    store.add(removed)
    store.add(kept)
    assert store.remove(0) is removed
    session = FakeSession(
        Path("world"),
        chunk_data={"Data": {"kept": 0, "removed": 0}},
    )
    handler = NbtCommitHandler(
        store=store,
        get_world_session=lambda: session,
        replace_world_session=lambda _session: None,
        get_page=lambda: None,
        refresh_stage=lambda: None,
        reload_current_target=lambda: None,
        warn=lambda _title, _message: None,
        info=lambda _title, _message: None,
        error=lambda _title, _message: None,
        handle_error=lambda error, _title: (_ for _ in ()).throw(error),
        log=lambda _message, _level: None,
        session_factory=lambda path, _log: FakeSession(path),
    )

    handler.execute_commit()

    committed = session.queued[0][4]
    assert committed["Data"] == {"kept": 2, "removed": 0}


class FakeBlockService(BlockDataService):
    def __init__(self) -> None:
        self.replacement = None

    def clear_cache(self) -> None:
        pass

    def get_block_at(self, data, x, y, z):
        return SimpleNamespace(
            name="minecraft:stone",
            properties={"axis": "y"},
        )

    def set_block_at(self, data, x, y, z, block_name):
        self.replacement = (x, y, z, block_name)
        return SimpleNamespace(
            success=True,
            old_name="minecraft:stone",
            new_name=block_name,
            message=f"已替换为 {block_name}",
        )


class FakeNbtTree:
    def __init__(self) -> None:
        self.loaded = []

    def load_nbt(self, data, editable=True) -> None:
        self.loaded.append((data, editable))


def test_chunk_operations_query_replace_and_stage_complete_chunk() -> None:
    target = ChunkNbtTarget(Path("region/r.0.0.mca"), 0, 0, {"sections": []})
    service = FakeBlockService()
    tree = FakeNbtTree()
    staged = []
    messages = []
    result_text = ft.Text()
    block_name = ft.TextField(value="dirt")

    operations = ChunkOperations(
        objects_list=ft.Column(),
        nbt_tree=tree,
        target_label=ft.Text(),
        world_x_field=ft.TextField(value="3"),
        world_z_field=ft.TextField(value="5"),
        block_y_field=ft.TextField(value="64"),
        block_result=result_text,
        block_name_field=block_name,
        get_chunk_target=lambda: target,
        set_view_state=lambda label, edit_format: None,
        stage_change=lambda path, old, new, display: staged.append(
            (path, old, new, display)
        ),
        warn=lambda title, message: messages.append((title, message)),
        info=lambda title, message: messages.append((title, message)),
        handle_error=lambda error, title: messages.append((title, str(error))),
        block_service=service,
    )

    operations.query_block_at_current_coords()
    operations.replace_block_at_current_coords()

    assert result_text.value == "minecraft:stone [axis=y]"
    assert service.replacement == (3, 64, 5, "minecraft:dirt")
    assert staged == [
        (
            ["block", 3, 64, 5],
            "minecraft:stone",
            "minecraft:dirt",
            "方块 (3, 64, 5)",
        )
    ]
    assert tree.loaded == [(target.data, True)]
    assert messages[-1][0] == "方块替换"


def test_dimension_region_directory_mapping() -> None:
    assert NbtDataLoader._dimension_region_dir("overworld") == "region"
    assert NbtDataLoader._dimension_region_dir("the_nether") == "DIM-1/region"
    assert NbtDataLoader._dimension_region_dir("the_end") == "DIM1/region"
    assert (
        NbtDataLoader._dimension_region_dir("mod:moon")
        == "dimensions/mod:moon/region"
    )


class NbtTabHarness(NbtTabMixin):
    def __init__(self) -> None:
        self.app = cast(Any, SimpleNamespace(
            page=None,
            warn_dialog=lambda title, message: None,
            info_dialog=lambda title, message: None,
            error_dialog=lambda title, message: None,
            handle_exception=lambda error, title=None: None,
            log=lambda message, level="INFO": None,
            save_file=lambda **kwargs: None,
        ))
        self.page = None
        self.world_session = None
        self.current_uuid = None
        self._current_dimension = "overworld"
        self._current_nbt_target = None
        self._current_nbt_label = "未加载 NBT"
        self._current_edit_format: NbtEditFormat = "nbt"
        self._current_chunk_target = None
        self._nbt_stage_store = NbtStageStore()
        self._tab_nbt = ft.Container()

    def _load_player_data(self, uuid: str) -> None:
        pass


def test_nbt_tab_builds_coordinators_after_controls() -> None:
    harness = NbtTabHarness()

    harness._build_nbt_tab()

    assert harness._tab_nbt.content is not None
    assert harness._stage_manager.get_staged_count() == 0
    assert harness._nbt_stage_status.value == "暂存区: 0 个变更"
    assert len(harness._chunk_objects_list.controls) == 1
