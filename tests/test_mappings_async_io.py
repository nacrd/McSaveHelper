"""映射页面后台 I/O、取消与 generation 回归测试。"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.ui.components.uuid_table import UUIDMappingTable
from app.ui.views import mappings as mappings_module
from app.ui.views.mappings import MappingsView
from app.ui.views.mappings_operations import _LatestOperationGroup


class _QueuedUi:
    """保存 UI 回调，允许测试显式控制投影时机。"""

    def __init__(self) -> None:
        self.callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
        self.enqueued = threading.Event()

    def post(
        self,
        page: object,
        callback: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> None:
        del page

        def invoke() -> None:
            callback(*args, **kwargs)

        self.callbacks.put(invoke)
        self.enqueued.set()

    def wait_for_callback(self) -> None:
        assert self.enqueued.wait(timeout=2)
        self.enqueued.clear()

    def drain(self) -> None:
        while True:
            try:
                self.callbacks.get_nowait()()
            except queue.Empty:
                return


class _Config:
    def __init__(self) -> None:
        self.custom_uuid_mappings: dict[str, str] = {}
        self.saved: list[tuple[int, dict[str, str]]] = []
        self.save_called = threading.Event()

    def save(self) -> None:
        self.saved.append(
            (threading.get_ident(), dict(self.custom_uuid_mappings))
        )
        self.save_called.set()


class _ItemService:
    def __init__(self) -> None:
        self.load_started = threading.Event()
        self.load_release = threading.Event()
        self.load_threads: list[int] = []

    def get_custom_item_mappings(self) -> dict[str, str]:
        return {}

    def load_custom_mapping_file(self, path: Path) -> int:
        del path
        self.load_threads.append(threading.get_ident())
        self.load_started.set()
        assert self.load_release.wait(timeout=2)
        return 2

    def save_custom_mapping_file(self, path: Path) -> None:
        path.write_text("{}", encoding="utf-8")

    def set_item_mapping(self, item_id: str, display_name: str) -> None:
        del item_id, display_name

    def delete_item_mapping(self, item_id: str) -> bool:
        del item_id
        return False


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=8)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _fail_on_error(error: Exception) -> None:
    pytest.fail(str(error))


def _view_app(
    runtime: ExecutionRuntime,
    config: _Config,
    item: _ItemService | None = None,
    **values: object,
) -> Any:
    defaults: dict[str, object] = {
        "execution_runtime": runtime,
        "config": config,
        "item": item or _ItemService(),
        "page": object(),
        "translate": lambda key, default: default,
        "pick_file": lambda **kwargs: None,
        "pick_files": lambda **kwargs: [],
        "save_file": lambda **kwargs: None,
        "handle_exception": lambda *args, **kwargs: None,
        "info_dialog": lambda *args, **kwargs: None,
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def test_uuid_changes_are_coalesced_and_saved_off_ui_thread() -> None:
    runtime = _runtime()
    config = _Config()
    view = MappingsView(cast(Any, _view_app(runtime, config)))
    view._UUID_SAVE_DEBOUNCE_SECONDS = 0.05
    calling_thread = threading.get_ident()
    try:
        view._queue_uuid_mappings({"Alice": "first"})
        view._queue_uuid_mappings({"Alice": "second"})
        view._queue_uuid_mappings({"Alice": "latest"})

        assert config.custom_uuid_mappings == {"Alice": "latest"}
        assert config.save_called.wait(timeout=2)
    finally:
        view.dispose()
        runtime.shutdown(wait=True)

    assert len(config.saved) == 1
    saved_thread, saved_mappings = config.saved[0]
    assert saved_mappings == {"Alice": "latest"}
    assert saved_thread != calling_thread


def test_dispose_flushes_latest_uuid_mapping_still_queued() -> None:
    runtime = _runtime()
    config = _Config()
    blocker_started = threading.Event()
    blocker_release = threading.Event()

    def block_worker(token: object) -> None:
        del token
        blocker_started.set()
        assert blocker_release.wait(timeout=2)

    blocker = runtime.submit("test.block", block_worker)
    assert blocker_started.wait(timeout=2)
    view = MappingsView(cast(Any, _view_app(runtime, config)))
    calling_thread = threading.get_ident()
    try:
        view._queue_uuid_mappings({"Alice": "queued"})
        view.dispose()
        blocker_release.set()
        blocker.result(timeout=2)
    finally:
        blocker_release.set()
        runtime.shutdown(wait=True)

    assert config.saved == [(calling_thread, {"Alice": "queued"})]


def test_latest_operation_discards_old_and_closed_ui_callbacks() -> None:
    runtime = _runtime()
    ui = _QueuedUi()
    applied: list[str] = []
    group = _LatestOperationGroup(
        runtime,
        "test_mappings",
        lambda callback: ui.post(None, callback),
    )
    try:
        group.submit("load", lambda token: "old", applied.append, _fail_on_error)
        ui.wait_for_callback()
        group.submit("load", lambda token: "new", applied.append, _fail_on_error)
        ui.wait_for_callback()
        ui.drain()
        assert applied == ["new"]

        group.submit("load", lambda token: "late", applied.append, _fail_on_error)
        ui.wait_for_callback()
        group.close()
        ui.drain()
        assert applied == ["new"]
    finally:
        group.close()
        runtime.shutdown(wait=True)


def test_uuid_import_reads_in_worker_and_applies_only_on_ui_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    config = _Config()
    ui = _QueuedUi()
    source = tmp_path / "players.txt"
    source.write_text("Alice uuid-a\n", encoding="utf-8")
    read_started = threading.Event()
    read_release = threading.Event()
    read_threads: list[int] = []
    original_read = UUIDMappingTable.read_mappings_file

    def read_mappings(path: Path) -> dict[str, str]:
        read_threads.append(threading.get_ident())
        read_started.set()
        assert read_release.wait(timeout=2)
        return original_read(path)

    monkeypatch.setattr(mappings_module, "run_on_ui", ui.post)
    monkeypatch.setattr(UUIDMappingTable, "read_mappings_file", read_mappings)
    app = _view_app(
        runtime,
        config,
        pick_file=lambda **kwargs: str(source),
    )
    view = MappingsView(cast(Any, app))
    calling_thread = threading.get_ident()
    try:
        assert view._on_uuid_import() is None
        assert read_started.wait(timeout=2)
        assert view._table.get_mappings() == {}
        read_release.set()
        ui.wait_for_callback()
        assert view._table.get_mappings() == {}

        ui.drain()
        assert view._table.get_mappings() == {"Alice": "uuid-a"}
        assert config.custom_uuid_mappings == {"Alice": "uuid-a"}
    finally:
        read_release.set()
        view.dispose()
        runtime.shutdown(wait=True)

    assert len(read_threads) == 1
    assert read_threads[0] != calling_thread


def test_uuid_export_writes_in_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    config = _Config()
    target = tmp_path / "players.txt"
    write_started = threading.Event()
    write_release = threading.Event()
    write_done = threading.Event()
    write_threads: list[int] = []
    original_write = UUIDMappingTable.write_mappings_file

    def write_mappings(path: Path, mappings: dict[str, str]) -> int:
        write_threads.append(threading.get_ident())
        write_started.set()
        assert write_release.wait(timeout=2)
        count = original_write(path, mappings)
        write_done.set()
        return count

    monkeypatch.setattr(UUIDMappingTable, "write_mappings_file", write_mappings)
    app = _view_app(
        runtime,
        config,
        save_file=lambda **kwargs: str(target),
    )
    view = MappingsView(cast(Any, app))
    calling_thread = threading.get_ident()
    try:
        assert view._on_uuid_export({"Bob": "uuid-b", "Alice": "uuid-a"}) is None
        assert write_started.wait(timeout=2)
        assert not target.exists()
        write_release.set()
        assert write_done.wait(timeout=2)
    finally:
        write_release.set()
        view.dispose()
        runtime.shutdown(wait=True)

    assert write_threads[0] != calling_thread
    assert target.read_text(encoding="utf-8") == "Alice uuid-a\nBob uuid-b\n"


def test_item_json_import_runs_in_worker_and_updates_status_on_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    config = _Config()
    item = _ItemService()
    ui = _QueuedUi()
    source = tmp_path / "items.json"
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mappings_module, "run_on_ui", ui.post)
    app = _view_app(
        runtime,
        config,
        item,
        pick_file=lambda **kwargs: str(source),
    )
    view = MappingsView(cast(Any, app))
    calling_thread = threading.get_ident()
    try:
        view._import_json(cast(Any, None))
        assert item.load_started.wait(timeout=2)
        assert view._item_mapping_status.value == ""
        item.load_release.set()
        ui.wait_for_callback()
        assert view._item_mapping_status.value == ""

        ui.drain()
        assert view._item_mapping_status.value == "已导入 2 个映射。"
    finally:
        item.load_release.set()
        view.dispose()
        runtime.shutdown(wait=True)

    assert item.load_threads[0] != calling_thread


def test_uuid_mapping_file_parsing_and_atomic_sorted_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text_path = tmp_path / "players.txt"
    text_path.write_text(
        "\ufeff# comment\nAlice uuid-a\ninvalid\nBob uuid-b extra\n",
        encoding="utf-8",
    )
    csv_path = tmp_path / "players.csv"
    csv_path.write_text(
        "# comment,ignored\nAlice,uuid-a\ninvalid\nBob,uuid-b,extra\n",
        encoding="utf-8",
    )

    assert UUIDMappingTable.read_mappings_file(text_path) == {
        "Alice": "uuid-a",
        "Bob": "uuid-b",
    }
    assert UUIDMappingTable.read_mappings_file(csv_path) == {
        "Alice": "uuid-a",
        "Bob": "uuid-b",
    }
    with pytest.raises(FileNotFoundError):
        UUIDMappingTable.read_mappings_file(tmp_path / "missing.txt")

    written: dict[str, object] = {}

    def atomic_write(path: Path, content: str, **kwargs: object) -> None:
        written.update(path=path, content=content, kwargs=kwargs)

    monkeypatch.setattr(
        "app.ui.components.uuid_table.atomic_write_text",
        atomic_write,
    )
    count = UUIDMappingTable.write_mappings_file(
        tmp_path / "output.txt",
        {"Bob": "uuid-b", "Alice": "uuid-a", "": "ignored"},
    )

    assert count == 2
    assert written == {
        "path": tmp_path / "output.txt",
        "content": "Alice uuid-a\nBob uuid-b\n",
        "kwargs": {"newline": "\n"},
    }
