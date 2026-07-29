"""Tests for the typed NBT staging and commit boundary."""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, Callable, Iterator, cast

import flet as ft
import pytest

from app.models.nbt_edit import (
    ChunkNbtTarget,
    NbtChange,
    NbtEditFormat,
    NbtStageStore,
)
from app.presenters.nbt_view_state import NbtViewState
from app.services.block_data_service import BlockDataService
from app.services.execution_runtime import (
    ExecutionRuntime,
    OperationCancelledError,
)
from app.ui.views.explorer.nbt.chunk_operations import ChunkOperations
from app.ui.views.explorer.nbt.nbt_data_loader import NbtDataLoader
from app.ui.views.explorer.nbt.nbt_commit_handler import (
    NbtCommitExecution,
    NbtCommitHandler,
    NbtCommitMessages,
    NbtCommitUi,
)
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
    def __init__(
        self,
        world_path: Path,
        chunk_data: Any = None,
        commit_results: list[bool] | None = None,
    ) -> None:
        self.world_path = world_path
        self.queued = []
        self.committed_with_backup = False
        self.chunk_data = chunk_data or {"Data": {"value": 1}, "sections": []}
        self.commit_results = commit_results if commit_results is not None else [True]
        self.batches: list[FakeSession] = []

    def new_action_session(self) -> "FakeSession":
        batch = FakeSession(
            self.world_path,
            self.chunk_data,
            self.commit_results,
        )
        self.batches.append(batch)
        return batch

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

    def commit(
        self,
        backup: bool = True,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        del cancel_check
        self.committed_with_backup = backup
        return self.commit_results.pop(0)


class BlockingFakeSession(FakeSession):
    """Fake action session that exposes deterministic commit checkpoints."""

    def __init__(
        self,
        world_path: Path,
        started: threading.Event,
        release: threading.Event,
        commit_results: list[bool] | None = None,
    ) -> None:
        super().__init__(world_path, commit_results=commit_results)
        self._started = started
        self._release = release

    def new_action_session(self) -> "BlockingFakeSession":
        batch = BlockingFakeSession(
            self.world_path,
            self._started,
            self._release,
            self.commit_results,
        )
        self.batches.append(batch)
        return batch

    def commit(
        self,
        backup: bool = True,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        self._started.set()
        if not self._release.wait(1):
            raise AssertionError("test did not release blocked NBT commit")
        if cancel_check is not None and cancel_check():
            return False
        return super().commit(backup=backup, cancel_check=cancel_check)


@pytest.fixture
def execution_runtime() -> Iterator[ExecutionRuntime]:
    """Provide an application-like runtime and close all workers after a test."""
    runtime = ExecutionRuntime()
    try:
        yield runtime
    finally:
        runtime.shutdown(wait=True)


@dataclass
class _CommitHarness:
    handler: NbtCommitHandler
    callback_done: threading.Event
    refreshed: list[str]
    messages: list[tuple[str, str]]
    handled_errors: list[tuple[str, Exception]]
    logs: list[tuple[str, str]]

    def execute(self) -> None:
        """Run one background commit and wait for its UI projection."""
        self.callback_done.clear()
        handle = self.handler.execute_commit()
        assert handle is not None
        handle.result(timeout=1)
        assert self.callback_done.wait(1)


def _commit_harness(
    store: NbtStageStore,
    session: FakeSession,
    runtime: ExecutionRuntime,
    *,
    reload_world: Callable[[Path], None] | None = None,
    is_world_current: Callable[[Path], bool] | None = None,
    get_generation: Callable[[], int] | None = None,
) -> _CommitHarness:
    """Build a deterministic handler with a synchronous fake UI dispatcher."""
    refreshed: list[str] = []
    messages: list[tuple[str, str]] = []
    handled_errors: list[tuple[str, Exception]] = []
    logs: list[tuple[str, str]] = []
    callback_done = threading.Event()

    def post_to_ui(callback: Callable[[], None]) -> None:
        try:
            callback()
        finally:
            callback_done.set()

    selected_reload = reload_world or (
        lambda path: refreshed.append(str(path))
    )
    handler = NbtCommitHandler(
        store=store,
        get_world_session=lambda: session,
        execution=NbtCommitExecution(
            scope=runtime.create_scope("nbt_commit_test"),
            post_to_ui=post_to_ui,
            get_generation=get_generation or (lambda: 1),
            is_world_current=is_world_current or (lambda _path: True),
            reload_world=selected_reload,
        ),
        ui=NbtCommitUi(
            get_page=lambda: None,
            refresh_stage=lambda: refreshed.append("stage"),
            warn=lambda title, message: messages.append((title, message)),
            info=lambda title, message: messages.append((title, message)),
            error=lambda title, message: messages.append((title, message)),
            handle_error=lambda error, title: handled_errors.append(
                (title, error)
            ),
            log=lambda message, level: logs.append((level, message)),
        ),
        messages=NbtCommitMessages(
            world_changed=("存档已切换", "当前存档已改变，请重新打开提交预览。"),
            busy=("提交进行中", "已有 NBT 提交正在执行。"),
            cancelled=("提交已取消", "原存档保持不变。"),
            queue_full=("后台任务繁忙", "请稍后重试。"),
        ),
    )
    return _CommitHarness(
        handler=handler,
        callback_done=callback_done,
        refreshed=refreshed,
        messages=messages,
        handled_errors=handled_errors,
        logs=logs,
    )


def test_commit_handler_queues_typed_changes_and_refreshes_session(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    chunk_data = {"Data": {"value": 4}, "sections": []}
    chunk_target = ChunkNbtTarget(Path("region/r.0.0.mca"), 1, 2, chunk_data)
    store.add(_change())
    store.add(_change(target=Path("stats/test.json"), format="json"))
    store.add(_change(target=chunk_target, format="chunk"))
    # Multiple edits to one chunk must still queue one complete chunk write.
    store.add(_change(target=chunk_target, format="chunk", new_value=4))

    session = FakeSession(Path("world"))
    harness = _commit_harness(store, session, execution_runtime)

    harness.execute()
    batch = session.batches[0]

    assert [queued[0] for queued in batch.queued] == ["nbt", "json", "chunk"]
    assert batch.committed_with_backup is True
    assert not store
    assert harness.refreshed == ["stage", "world"]
    assert harness.messages[-1][0] == "提交完成"


def test_commit_success_is_not_reclassified_when_world_reload_fails(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    store.add(_change())
    session = FakeSession(Path("world"))

    def fail_reload(_path: Path) -> None:
        raise RuntimeError("reload failed")

    harness = _commit_harness(
        store,
        session,
        execution_runtime,
        reload_world=fail_reload,
    )

    harness.execute()
    batch = session.batches[0]

    assert batch.committed_with_backup is True
    assert not store
    assert harness.handled_errors == []
    assert harness.messages[-1][0] == "提交完成"
    assert harness.logs == [
        ("WARNING", "提交成功，但刷新世界会话失败: reload failed")
    ]


def test_chunk_commit_replays_only_remaining_changes_from_disk(
    execution_runtime: ExecutionRuntime,
) -> None:
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
    harness = _commit_harness(store, session, execution_runtime)

    harness.execute()

    committed = session.batches[0].queued[0][4]
    assert committed["Data"] == {"kept": 2, "removed": 0}


def test_commit_retry_uses_a_fresh_action_queue(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    store.add(_change(old_value=None, new_value=2, path=["Data", "items", 0]))
    session = FakeSession(Path("world"), commit_results=[False, True])
    harness = _commit_harness(store, session, execution_runtime)

    harness.execute()
    assert len(store) == 1
    harness.execute()

    assert len(session.batches) == 2
    assert [len(batch.queued) for batch in session.batches] == [1, 1]
    assert not store
    assert [message[0] for message in harness.messages] == [
        "提交失败",
        "提交完成",
    ]


def test_commit_rejects_staged_world_after_current_save_switch(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    store.add(_change())
    session = FakeSession(Path("world-a"))
    harness = _commit_harness(
        store,
        session,
        execution_runtime,
        is_world_current=lambda _path: False,
    )

    assert harness.handler.execute_commit() is None

    assert session.batches == []
    assert len(store) == 1
    assert harness.messages == [
        ("存档已切换", "当前存档已改变，请重新打开提交预览。")
    ]


def test_commit_returns_before_io_and_preserves_newly_staged_change(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    committed_change = _change(new_value=2)
    later_change = _change(new_value=3)
    store.add(committed_change)
    started = threading.Event()
    release = threading.Event()
    session = BlockingFakeSession(Path("world"), started, release)
    harness = _commit_harness(store, session, execution_runtime)

    handle = harness.handler.execute_commit()

    assert handle is not None
    assert started.wait(1)
    assert store.changes == (committed_change,)
    store.add(later_change)
    release.set()
    handle.result(timeout=1)
    assert harness.callback_done.wait(1)
    assert store.changes == (later_change,)


def test_commit_drops_completion_after_world_generation_changes(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    store.add(_change())
    session = FakeSession(Path("world"))
    generation = [1]
    callbacks: list[Callable[[], None]] = []
    callback_posted = threading.Event()
    messages: list[tuple[str, str]] = []
    logs: list[tuple[str, str]] = []

    def post_to_ui(callback: Callable[[], None]) -> None:
        callbacks.append(callback)
        callback_posted.set()

    handler = NbtCommitHandler(
        store=store,
        get_world_session=lambda: session,
        execution=NbtCommitExecution(
            scope=execution_runtime.create_scope("stale_nbt_commit_test"),
            post_to_ui=post_to_ui,
            get_generation=lambda: generation[0],
            is_world_current=lambda _path: True,
            reload_world=lambda _path: None,
        ),
        ui=NbtCommitUi(
            get_page=lambda: None,
            refresh_stage=lambda: (_ for _ in ()).throw(
                AssertionError("stale callback refreshed stage")
            ),
            warn=lambda title, message: messages.append((title, message)),
            info=lambda title, message: messages.append((title, message)),
            error=lambda title, message: messages.append((title, message)),
            handle_error=lambda error, title: messages.append(
                (title, str(error))
            ),
            log=lambda message, level: logs.append((level, message)),
        ),
        messages=NbtCommitMessages(
            world_changed=("changed", "changed"),
            busy=("busy", "busy"),
            cancelled=("cancelled", "cancelled"),
            queue_full=("full", "full"),
        ),
    )

    handle = handler.execute_commit()
    assert handle is not None
    handle.result(timeout=1)
    assert callback_posted.wait(1)
    generation[0] += 1
    callbacks.pop()()

    assert len(store) == 1
    assert messages == []
    assert logs == [("INFO", "丢弃过期 NBT 提交回调: world")]


def test_commit_cancel_keeps_staged_changes(
    execution_runtime: ExecutionRuntime,
) -> None:
    store = NbtStageStore()
    store.add(_change())
    started = threading.Event()
    release = threading.Event()
    session = BlockingFakeSession(Path("world"), started, release)
    harness = _commit_harness(store, session, execution_runtime)

    handle = harness.handler.execute_commit()
    assert handle is not None
    assert started.wait(1)
    assert handle.cancel() is True
    release.set()
    with pytest.raises(OperationCancelledError):
        handle.result(timeout=1)
    assert harness.callback_done.wait(1)

    assert len(store) == 1
    assert harness.messages[-1][0] == "提交已取消"


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
    def __init__(self, runtime: ExecutionRuntime) -> None:
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
        self._nbt_view_state = NbtViewState()
        self._nbt_stage_store = NbtStageStore()
        self._tab_nbt = ft.Container()
        self._task_scope = runtime.create_scope("nbt_tab_test")
        self._world_load_generation = 0

    def _load_player_data(self, uuid: str) -> None:
        pass


def test_nbt_tab_builds_coordinators_after_controls(
    execution_runtime: ExecutionRuntime,
) -> None:
    harness = NbtTabHarness(execution_runtime)

    harness._build_nbt_tab()

    assert harness._tab_nbt.content is not None
    assert harness._stage_manager.get_staged_count() == 0
    assert harness._nbt_stage_status.value == "暂存区: 0 个变更"
    assert len(harness._chunk_objects_list.controls) == 1
