"""实体/方块搜索控制器并发、取消与迟到回调测试。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from app.controllers.entity_block_search_controller import (
    EntityBlockExportCompletion,
    EntityBlockSearchBusyError,
    EntityBlockSearchCompletion,
    EntityBlockSearchController,
    EntityBlockSearchUiPorts,
)
from app.services.entity_block_search.models import SearchCondition, SearchResult
from app.services.entity_block_search_service import EntityBlockSearchService
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
    OperationScope,
)


class _UiQueue:
    """保存 UI 投递，允许测试在世界切换后再执行回调。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[], None]] = []
        self.posted = threading.Event()

    def dispatch(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callbacks.append(callback)
            self.posted.set()

    def drain(self) -> None:
        while True:
            with self._lock:
                if not self._callbacks:
                    self.posted.clear()
                    return
                callback = self._callbacks.pop(0)
            callback()


@dataclass
class _UiRecorder:
    """记录控制器通过类型化端口投递的 UI 事件。"""

    events: list[str] = field(default_factory=list)
    searches: list[EntityBlockSearchCompletion] = field(default_factory=list)
    exports: list[EntityBlockExportCompletion] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)

    def ports(self, ui_queue: _UiQueue) -> EntityBlockSearchUiPorts:
        return EntityBlockSearchUiPorts(
            dispatch=ui_queue.dispatch,
            search_started=lambda: self.events.append("search_started"),
            search_succeeded=self._search_succeeded,
            search_failed=self._search_failed,
            search_cancelled=lambda: self.events.append("search_cancelled"),
            export_started=lambda: self.events.append("export_started"),
            export_succeeded=self._export_succeeded,
            export_failed=self._export_failed,
            export_cancelled=lambda: self.events.append("export_cancelled"),
        )

    def _search_succeeded(
        self,
        completion: EntityBlockSearchCompletion,
    ) -> None:
        self.events.append("search_succeeded")
        self.searches.append(completion)

    def _search_failed(self, error: Exception) -> None:
        self.events.append("search_failed")
        self.errors.append(error)

    def _export_succeeded(
        self,
        completion: EntityBlockExportCompletion,
    ) -> None:
        self.events.append("export_succeeded")
        self.exports.append(completion)

    def _export_failed(self, error: Exception) -> None:
        self.events.append("export_failed")
        self.errors.append(error)


class _ControlledSearchService(EntityBlockSearchService):
    """可阻塞搜索或导出的最小服务替身。"""

    def __init__(
        self,
        *,
        block_search: bool = False,
        block_export: bool = False,
    ) -> None:
        super().__init__()
        self.block_search = block_search
        self.block_export = block_export
        self.search_started = threading.Event()
        self.search_release = threading.Event()
        self.export_started = threading.Event()
        self.export_release = threading.Event()

    def search_condition(
        self,
        condition: SearchCondition,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ) -> List[SearchResult]:
        del progress_callback, log_callback
        self.search_started.set()
        if self.block_search and not self.search_release.wait(2):
            raise TimeoutError("搜索测试未获准继续")
        return [
            SearchResult(
                condition.search_type,
                condition.target,
                (1, 64, 2),
                condition.dimensions[0],
            )
        ]

    def export_results(
        self,
        results: List[SearchResult],
        output_path: Path,
    ) -> None:
        self.export_started.set()
        if self.block_export and not self.export_release.wait(2):
            raise TimeoutError("导出测试未获准继续")
        super().export_results(results, output_path)


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=2, queue_capacity=4)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _world(tmp_path: Path, name: str = "world") -> Path:
    world = tmp_path / name
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    return world


def _condition(world: Path, target: str = "zombie") -> SearchCondition:
    return SearchCondition("entity", target, ["overworld"], world)


def _controller(
    runtime: ExecutionRuntime,
    service: EntityBlockSearchService,
    ui_queue: _UiQueue,
    recorder: _UiRecorder,
) -> tuple[EntityBlockSearchController, OperationScope]:
    scope = runtime.create_scope("entity_block_search_test")
    controller = EntityBlockSearchController(
        service,
        scope,
        recorder.ports(ui_queue),
    )
    return controller, scope


def test_view_delegates_lifecycle_and_stays_below_budget() -> None:
    project_root = Path(__file__).resolve().parents[1]
    view_source = (
        project_root / "app/ui/views/entity_block_search.py"
    ).read_text(encoding="utf-8")
    controller_source = (
        project_root / "app/controllers/entity_block_search_controller.py"
    ).read_text(encoding="utf-8")

    assert len(view_source.splitlines()) < 700
    assert "EntityBlockSearchController" in view_source
    assert "_run_search_worker" not in view_source
    assert "flet" not in controller_source


def test_search_and_export_use_typed_results_and_expected_lanes(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = _ControlledSearchService()
    ui_queue = _UiQueue()
    recorder = _UiRecorder()
    controller, scope = _controller(runtime, service, ui_queue, recorder)
    world = _world(tmp_path)
    controller.select_world(world)

    try:
        search = controller.start_search(_condition(world))
        assert search is not None
        assert search.lane is ExecutionLane.CPU
        completion = search.result(timeout=2)
        assert ui_queue.posted.wait(2)
        ui_queue.drain()

        assert completion.target == "zombie"
        assert recorder.events == ["search_started", "search_succeeded"]
        assert recorder.searches[0].results[0].target_id == "zombie"
        assert controller.is_searching is False

        output = tmp_path / "results.txt"
        export = controller.start_export(completion.results, output)
        assert export is not None
        assert export.lane is ExecutionLane.IO
        export_completion = export.result(timeout=2)
        assert ui_queue.posted.wait(2)
        ui_queue.drain()

        assert export_completion.output_path == output
        assert "zombie" in output.read_text(encoding="utf-8")
        assert recorder.events[-2:] == ["export_started", "export_succeeded"]
        assert controller.is_exporting is False
    finally:
        controller.close()
        scope.close()
        runtime.shutdown(wait=True)


def test_world_switch_cancels_active_search_and_rejects_concurrency(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = _ControlledSearchService(block_search=True)
    ui_queue = _UiQueue()
    recorder = _UiRecorder()
    controller, scope = _controller(runtime, service, ui_queue, recorder)
    first_world = _world(tmp_path, "first")
    second_world = _world(tmp_path, "second")
    controller.select_world(first_world)

    search = controller.start_search(_condition(first_world, "old"))
    assert search is not None
    assert service.search_started.wait(2)
    try:
        queued_result = SearchResult(
            "entity",
            "cow",
            (1, 64, 1),
            "overworld",
        )
        with pytest.raises(EntityBlockSearchBusyError):
            controller.start_export([queued_result], tmp_path / "x")
        with pytest.raises(EntityBlockSearchBusyError):
            controller.start_search(_condition(first_world, "duplicate"))

        controller.select_world(second_world)
        assert search.cancel_requested is True
        assert controller.is_searching is False
        service.search_release.set()
        with pytest.raises(OperationCancelledError):
            search.result(timeout=2)
        assert recorder.searches == []

        replacement = controller.start_search(_condition(second_world, "new"))
        assert replacement is not None
        assert replacement.result(timeout=2).target == "new"
        assert ui_queue.posted.wait(2)
        ui_queue.drain()
        assert recorder.searches[-1].target == "new"
    finally:
        service.search_release.set()
        controller.close()
        scope.close()
        runtime.shutdown(wait=True)


def test_queued_success_is_dropped_after_world_switch(tmp_path: Path) -> None:
    runtime = _runtime()
    service = _ControlledSearchService()
    ui_queue = _UiQueue()
    recorder = _UiRecorder()
    controller, scope = _controller(runtime, service, ui_queue, recorder)
    first_world = _world(tmp_path, "first")
    second_world = _world(tmp_path, "second")
    controller.select_world(first_world)

    try:
        handle = controller.start_search(_condition(first_world, "late"))
        assert handle is not None
        assert handle.result(timeout=2).target == "late"
        assert ui_queue.posted.wait(2)

        controller.select_world(second_world)
        ui_queue.drain()

        assert recorder.searches == []
        assert controller.is_searching is False
    finally:
        controller.close()
        scope.close()
        runtime.shutdown(wait=True)


def test_close_drops_late_export_but_preserves_committed_success(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = _ControlledSearchService(block_export=True)
    ui_queue = _UiQueue()
    recorder = _UiRecorder()
    controller, scope = _controller(runtime, service, ui_queue, recorder)
    world = _world(tmp_path)
    controller.select_world(world)
    result = SearchResult("entity", "cow", (2, 65, 3), "overworld")
    output = tmp_path / "export.txt"

    export = controller.start_export([result], output)
    assert export is not None
    assert service.export_started.wait(2)
    try:
        controller.close()
        controller.close()
        assert controller.is_closed is True
        assert scope.is_closed is False
        assert export.cancel_requested is True

        service.export_release.set()
        completion = export.result(timeout=2)
        assert completion.output_path == output
        assert export.cancelled is False
        assert output.is_file()
        assert recorder.exports == []
        with pytest.raises(RuntimeError, match="已经关闭"):
            controller.start_search(_condition(world))
    finally:
        service.export_release.set()
        scope.close()
        runtime.shutdown(wait=True)
