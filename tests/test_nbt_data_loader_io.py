"""NBT 数据加载 I/O 边界与迟到回调回归测试。"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
import json
from pathlib import Path
import threading
from typing import Any, Optional, cast

import flet as ft
import pytest

import core.nbt as nbtlib
from app.models.nbt_edit import ChunkNbtTarget, NbtEditFormat, NbtTarget
from app.services.execution_runtime import (
    CancellationToken,
    ExecutionLane,
    ExecutionRuntime,
    OperationCancelledError,
)
from app.ui.views.explorer.nbt.nbt_data_loader import NbtDataLoader
from app.ui.views.explorer.nbt.nbt_io_coordinator import NbtIoCoordinator
from app.ui.views.explorer.nbt.nbt_io_operations import (
    ChunkMissingError,
    export_json_payload,
    find_nbt_target_candidates,
    load_chunk_payload,
    load_world_json,
    load_world_nbt,
)
from app.ui.views.explorer.nbt_tree import exporter as nbt_exporter
from core.omni.world_session import WorldSession


class _ChunkSession:
    """只实现区块加载端口的测试会话。"""

    def __init__(self, world_path: Path, result: Optional[tuple[Any, Path]]) -> None:
        self.world_path = world_path
        self.result = result
        self.requests: list[tuple[Path, int, int]] = []

    def load_chunk_nbt(
        self,
        region_path: Path,
        chunk_x: int,
        chunk_z: int,
    ) -> Optional[tuple[Any, Path]]:
        self.requests.append((region_path, chunk_x, chunk_z))
        return self.result


class _QueuedPage:
    """记录 Flet async callable，允许测试控制 UI 消费时机。"""

    def __init__(self) -> None:
        self.tasks: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self.scheduled = threading.Event()

    def run_task(
        self,
        callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self.tasks.append(callback)
        self.scheduled.set()


class _FakeNbtTree:
    """记录 loader 投影的数据和可编辑标记。"""

    def __init__(self) -> None:
        self.loaded: list[tuple[Any, bool]] = []

    def load_nbt(self, data: Any, editable: bool = True) -> None:
        self.loaded.append((data, editable))

    def get_modified_data(self) -> None:
        return None


class _CancelBeforePublish(CancellationToken):
    """在临时文件完成后、原子发布前触发取消。"""

    def __init__(self) -> None:
        super().__init__()
        self._checks = 0

    def raise_if_cancelled(self) -> None:
        self._checks += 1
        if self._checks == 2:
            raise OperationCancelledError("test cancellation")


def test_nbt_io_operations_scan_and_load_world_files(tmp_path: Path) -> None:
    world = tmp_path / "world"
    (world / "data").mkdir(parents=True)
    (world / "stats").mkdir()
    (world / "advancements").mkdir()
    level_path = world / "level.dat"
    nbtlib.File({
        "Data": nbtlib.Compound({"value": nbtlib.Int(4)}),
    }).save(level_path)
    (world / "data" / "z.dat").write_bytes(b"ignored")
    (world / "data" / "a.dat").write_bytes(b"ignored")
    stats_path = world / "stats" / "player.json"
    stats_path.write_text('{"jumps": 3}', encoding="utf-8")
    (world / "advancements" / "story.json").write_text(
        "{}",
        encoding="utf-8",
    )

    candidates = find_nbt_target_candidates(world)
    loaded_nbt = load_world_nbt(world, Path("level.dat"), None)
    loaded_json = load_world_json(world, Path("stats/player.json"), None)

    assert [path.as_posix() for _, path in candidates] == [
        "level.dat",
        "data/a.dat",
        "data/z.dat",
        "stats/player.json",
        "advancements/story.json",
    ]
    assert int(loaded_nbt["Data"]["value"]) == 4
    assert loaded_json == {"jumps": 3}


def test_world_file_loader_rejects_escape_and_observes_cancel(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    world.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="当前存档目录内"):
        load_world_json(world, Path("../outside.json"), None)

    inside = world / "inside.json"
    inside.write_text("{}", encoding="utf-8")
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelledError):
        load_world_json(world, Path("inside.json"), token)


def test_chunk_loader_returns_canonical_relative_target(tmp_path: Path) -> None:
    world = tmp_path / "world"
    region_path = world / "region" / "r.0.0.mca"
    region_path.parent.mkdir(parents=True)
    region_path.write_bytes(b"")
    chunk_data = {"Data": {"value": 7}}
    session = _ChunkSession(world, (chunk_data, region_path))

    result = load_chunk_payload(
        cast(WorldSession, session),
        Path("region/r.0.0.mca"),
        "region/r.0.0.mca",
        2,
        -3,
        None,
    )

    assert result.region_path == Path("region/r.0.0.mca")
    assert result.data is chunk_data
    assert session.requests == [(Path("region/r.0.0.mca"), 2, -3)]

    session.result = None
    with pytest.raises(ChunkMissingError):
        load_chunk_payload(
            cast(WorldSession, session),
            Path("region/r.0.0.mca"),
            "region/r.0.0.mca",
            2,
            -3,
            None,
        )


def test_export_json_payload_preserves_nbt_values(tmp_path: Path) -> None:
    output_path = tmp_path / "export.json"
    output_path.write_text("old", encoding="utf-8")

    assert export_json_payload(
        {"value": nbtlib.Int(9)},
        output_path,
        None,
    )
    assert json.loads(output_path.read_text(encoding="utf-8")) == {"value": 9}


def test_export_cancel_before_publish_keeps_existing_file(tmp_path: Path) -> None:
    output_path = tmp_path / "export.json"
    output_path.write_text("old", encoding="utf-8")

    with pytest.raises(OperationCancelledError):
        export_json_payload(
            {"value": nbtlib.Int(9)},
            output_path,
            _CancelBeforePublish(),
        )

    assert output_path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [output_path]


def test_export_propagates_atomic_write_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "export.json"

    def fail_write(_path: Path, _content: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(
        "app.ui.views.explorer.nbt.nbt_io_operations.atomic_write_text",
        fail_write,
    )

    with pytest.raises(OSError, match="disk full"):
        export_json_payload({"value": 9}, output_path, None)


def test_legacy_nbt_export_publish_failure_keeps_old_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "export.json"
    output_path.write_text("old", encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("publish failed")

    monkeypatch.setattr("core.io_atomic.os.replace", fail_replace)

    assert nbt_exporter.export_json({"value": 9}, str(output_path)) is False
    assert output_path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [output_path]


@pytest.mark.parametrize("invalidate", ["close", "generation"])
def test_io_coordinator_drops_queued_stale_ui_callback(invalidate: str) -> None:
    runtime = ExecutionRuntime()
    scope = runtime.create_scope("nbt_io_test")
    page = _QueuedPage()
    is_current = [True]
    delivered: list[int] = []
    coordinator = NbtIoCoordinator(
        task_scope=scope,
        page=cast(Any, page),
        get_world_session=lambda: None,
        handle_error=lambda _error, _title: None,
    )
    try:
        coordinator.submit(
            "load",
            lambda _token: 7,
            delivered.append,
            "加载失败",
            request_guard=lambda: is_current[0],
        )
        assert page.scheduled.wait(1)

        if invalidate == "close":
            coordinator.close()
        else:
            is_current[0] = False
        asyncio.run(page.tasks.pop()())

        assert delivered == []
        assert runtime.snapshot().submitted_by_lane[ExecutionLane.IO] == 1
    finally:
        coordinator.close()
        scope.close()
        runtime.shutdown(wait=True)


def test_data_loader_keeps_headless_json_public_behavior(tmp_path: Path) -> None:
    world = tmp_path / "world"
    stats_path = world / "stats" / "player.json"
    stats_path.parent.mkdir(parents=True)
    stats_path.write_text('{"walked": 12}', encoding="utf-8")
    session = cast(WorldSession, _ChunkSession(world, None))
    target_states: list[
        tuple[Optional[NbtTarget], str, NbtEditFormat, Optional[ChunkNbtTarget]]
    ] = []
    tree = _FakeNbtTree()
    loader = NbtDataLoader(
        get_world_session=lambda: session,
        get_current_uuid=lambda: None,
        get_current_target=lambda: None,
        get_current_label=lambda: "未加载",
        get_dimension=lambda: "overworld",
        set_target_state=lambda target, label, edit_format, chunk: (
            target_states.append((target, label, edit_format, chunk))
        ),
        load_player_data=lambda _uuid: None,
        render_chunk_objects=lambda _data: None,
        query_current_block=lambda: None,
        target_dropdown=ft.Dropdown(),
        target_label=ft.Text(),
        region_file_field=ft.TextField(),
        chunk_x_field=ft.TextField(),
        chunk_z_field=ft.TextField(),
        world_x_field=ft.TextField(),
        world_z_field=ft.TextField(),
        nbt_tree=cast(Any, tree),
        warn=lambda _title, _message: None,
        info=lambda _title, _message: None,
        handle_error=lambda error, title: pytest.fail(f"{title}: {error}"),
        save_file=lambda **_kwargs: None,
    )

    loader.load_json_file(Path("stats/player.json"), "NBT 文件: player")

    assert target_states == [
        (Path("stats/player.json"), "JSON 文件: player", "json", None)
    ]
    assert tree.loaded == [({"walked": 12}, True)]
