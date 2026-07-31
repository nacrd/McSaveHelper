"""映射页「UUID 查询」后台任务与输入校验测试。"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.ui.views import mappings as mappings_module
from app.ui.views.mappings import MappingsView
from core.uuid_utils import NameHistoryEntry

_NOTCH = "069a79f4-44e9-4726-a5be-fca90e38aaf5"
_NOTCH_NORM = "069a79f444e94726a5befca90e38aaf5"
_UUID_A = "11111111-1111-1111-1111-111111111111"
_UUID_B = "22222222-2222-2222-2222-222222222222"


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


class _BlockingUuidService:
    """单次 UUID 姓名历史查询，直到测试释放才返回。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.uuids: list[str] = []
        self.worker_threads: list[int] = []

    def query_name_history(
        self,
        uuid: str,
        log_callback: object = None,
    ) -> list[NameHistoryEntry]:
        del log_callback
        self.uuids.append(uuid)
        self.worker_threads.append(threading.get_ident())
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("姓名历史查询未获准继续")
        return [NameHistoryEntry(name="Notch")]


class _MultiBlockingUuidService:
    """两次姓名历史查询，逐个释放；用于验证最新 generation 生效。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.all_started = threading.Event()
        self.uuids: list[str] = []
        self._releases: list[threading.Event] = []
        self._lock = threading.Lock()

    def query_name_history(
        self,
        uuid: str,
        log_callback: object = None,
    ) -> list[NameHistoryEntry]:
        del log_callback
        with self._lock:
            index = len(self.uuids)
            self.uuids.append(uuid)
            self._releases.append(threading.Event())
            if len(self.uuids) == 2:
                self.all_started.set()
        self.started.set()
        if not self._releases[index].wait(timeout=2):
            raise TimeoutError(f"姓名历史查询未获准继续: {uuid}")
        name = "玩家 A" if index == 0 else "玩家 B"
        return [NameHistoryEntry(name=name)]

    def release_index(self, index: int) -> None:
        self._releases[index].set()

    def release_all(self) -> None:
        for release in self._releases:
            release.set()


class _Config:
    def __init__(self) -> None:
        self.custom_uuid_mappings: dict[str, str] = {}


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=8)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _view_app(
    runtime: ExecutionRuntime,
    config: _Config,
    uuid_service: object,
) -> Any:
    return SimpleNamespace(
        execution_runtime=runtime,
        config=config,
        uuid=uuid_service,
        item=SimpleNamespace(
            get_custom_item_mappings=lambda: {},
            set_item_mapping=lambda *args: None,
            delete_item_mapping=lambda *args: False,
        ),
        texture=object(),
        page=object(),
        translate=lambda key, default: default,
        log=lambda message, level="INFO": None,
        pick_file=lambda **kwargs: None,
        pick_files=lambda **kwargs: [],
        save_file=lambda **kwargs: None,
        handle_exception=lambda *args, **kwargs: None,
        info_dialog=lambda *args, **kwargs: None,
    )


def test_uuid_name_query_runs_in_worker_and_applies_on_ui_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    config = _Config()
    uuid_service = _BlockingUuidService()
    ui = _QueuedUi()
    monkeypatch.setattr(mappings_module, "run_on_ui", ui.post)
    view = MappingsView(cast(Any, _view_app(runtime, config, uuid_service)))
    calling_thread = threading.get_ident()
    try:
        view._uuid_query_field.value = _NOTCH
        view._on_uuid_query()
        assert uuid_service.started.wait(timeout=2)
        assert view._uuid_query_result.value == "正在查询..."
        assert uuid_service.uuids == [_NOTCH_NORM]

        uuid_service.release.set()
        ui.wait_for_callback()
        assert view._uuid_query_result.value == "正在查询..."  # 未 drain 不应用
        ui.drain()
        assert "当前名称: Notch" in view._uuid_query_result.value
    finally:
        uuid_service.release.set()
        view.dispose()
        runtime.shutdown(wait=True)

    assert uuid_service.worker_threads[0] != calling_thread


def test_uuid_name_query_drops_stale_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    config = _Config()
    uuid_service = _MultiBlockingUuidService()
    ui = _QueuedUi()
    monkeypatch.setattr(mappings_module, "run_on_ui", ui.post)
    view = MappingsView(cast(Any, _view_app(runtime, config, uuid_service)))
    try:
        view._uuid_query_field.value = _UUID_A
        view._on_uuid_query()
        assert uuid_service.started.wait(timeout=2)

        view._uuid_query_field.value = _UUID_B
        view._on_uuid_query()  # 取消第一个并排队第二个（IO 单线程）

        uuid_service.release_index(0)  # 第一个完成但应被丢弃 → 第二个开始
        assert uuid_service.all_started.wait(timeout=2)

        uuid_service.release_index(1)  # 第二个完成并投递
        ui.wait_for_callback()
        ui.drain()
        assert "玩家 B" in view._uuid_query_result.value
        assert "玩家 A" not in view._uuid_query_result.value
        assert ui.callbacks.empty()
    finally:
        uuid_service.release_all()
        view.dispose()
        runtime.shutdown(wait=True)


def test_uuid_name_query_rejects_invalid_uuid_without_worker() -> None:
    runtime = _runtime()
    config = _Config()
    uuid_service = _BlockingUuidService()
    view = MappingsView(cast(Any, _view_app(runtime, config, uuid_service)))
    try:
        view._uuid_query_field.value = "not-a-uuid"
        view._on_uuid_query()

        assert "UUID 格式无效" in view._uuid_query_result.value
        assert not uuid_service.started.is_set()
    finally:
        view.dispose()
        runtime.shutdown(wait=True)


def test_uuid_name_query_empty_input_is_noop() -> None:
    runtime = _runtime()
    config = _Config()
    uuid_service = _BlockingUuidService()
    view = MappingsView(cast(Any, _view_app(runtime, config, uuid_service)))
    try:
        view._uuid_query_field.value = "   "
        view._on_uuid_query()

        assert view._uuid_query_result.value == "在此显示查询结果"
        assert not uuid_service.started.is_set()
    finally:
        view.dispose()
        runtime.shutdown(wait=True)
