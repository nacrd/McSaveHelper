"""Save repair controller generation and cancellation behavior."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable, Optional, cast

from app.controllers.save_repair_controller import (
    RepairOptions,
    SaveRepairController,
    SaveRepairUiPorts,
)
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.save_repair.models import DetectReport, RepairReport
from app.services.save_repair_service import SaveRepairService
from core.types import LogCallback


ProgressMessageCallback = Callable[[float, str], None]


class _FakeRepairService:
    def __init__(self) -> None:
        self.cancel_calls = 0
        self.detect_calls: list[Path] = []
        self.repair_calls: list[Path] = []
        self.detect_started = threading.Event()
        self.detect_release = threading.Event()

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.detect_release.set()

    def detect_world(
        self,
        world_path: Path,
        progress_callback: Optional[ProgressMessageCallback] = None,
        log_callback: Optional[LogCallback] = None,
    ) -> DetectReport:
        self.detect_calls.append(world_path)
        if progress_callback is not None:
            progress_callback(0.25, "扫描中")
        if log_callback is not None:
            log_callback("旧世界日志", "INFO")
        self.detect_started.set()
        self.detect_release.wait(timeout=2)
        return DetectReport()

    def repair_world(
        self,
        world_path: Path,
        **kwargs: object,
    ) -> RepairReport:
        del kwargs
        self.repair_calls.append(world_path)
        return RepairReport(success=True)


class _UiRecorder:
    def __init__(self) -> None:
        self.progress: list[tuple[str, float]] = []
        self.logs: list[tuple[str, str]] = []
        self.detect_reports: list[DetectReport] = []
        self.repair_reports: list[RepairReport] = []
        self.errors: list[Exception] = []
        self.finished = 0

    def ports(self) -> SaveRepairUiPorts:
        return SaveRepairUiPorts(
            show_progress=lambda message: self.progress.append((message, 0.0)),
            update_progress=lambda message, value: self.progress.append(
                (message, value)
            ),
            append_log=lambda message, level: self.logs.append((message, level)),
            show_detect_report=self.detect_reports.append,
            show_repair_report=self.repair_reports.append,
            show_detect_error=self.errors.append,
            show_repair_error=self.errors.append,
            finish_operation=self._finish,
        )

    def _finish(self) -> None:
        self.finished += 1


class _QueuedUi:
    def __init__(self, expected: int) -> None:
        self._callbacks: queue.Queue[Callable[[], None]] = queue.Queue()
        self._expected = expected
        self.ready = threading.Event()

    def post(self, callback: Callable[[], None]) -> None:
        self._callbacks.put(callback)
        if self._callbacks.qsize() >= self._expected:
            self.ready.set()

    def drain(self) -> None:
        while True:
            try:
                callback = self._callbacks.get_nowait()
            except queue.Empty:
                return
            callback()


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def test_world_switch_discards_callbacks_already_queued_for_old_world(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = _FakeRepairService()
    ui = _UiRecorder()
    queued_ui = _QueuedUi(expected=4)
    scope = runtime.create_scope("test_save_repair_switch")
    controller = SaveRepairController(
        cast(SaveRepairService, service),
        scope,
        ui.ports(),
        queued_ui.post,
    )
    first_world = tmp_path / "world-a"

    try:
        controller.start_detect(first_world)
        assert service.detect_started.wait(timeout=2)

        controller.select_world(tmp_path / "world-b")
        assert queued_ui.ready.wait(timeout=2)
        assert ui.progress == []
        assert ui.logs == []

        queued_ui.drain()

        assert service.cancel_calls == 1
        assert service.detect_calls == [first_world.absolute()]
        assert ui.progress == []
        assert ui.logs == []
        assert ui.detect_reports == []
        assert ui.finished == 1
    finally:
        controller.close()
        scope.close()
        runtime.shutdown(wait=True)


def test_cancel_closes_domain_and_runtime_paths_before_queued_repair_runs(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    service = _FakeRepairService()
    ui = _UiRecorder()
    blocker_started = threading.Event()
    blocker_release = threading.Event()
    blocker = runtime.submit(
        "block_io_lane",
        lambda token: (
            blocker_started.set(),
            blocker_release.wait(timeout=2),
        ),
    )
    assert blocker_started.wait(timeout=2)
    scope = runtime.create_scope("test_save_repair_cancel")
    controller = SaveRepairController(
        cast(SaveRepairService, service),
        scope,
        ui.ports(),
        lambda callback: callback(),
    )

    try:
        controller.start_repair(
            tmp_path / "world",
            RepairOptions(True, True, True, True),
        )
        controller.cancel()
        blocker_release.set()
        blocker.result(timeout=2)

        assert service.cancel_calls == 1
        assert service.repair_calls == []
        assert ui.repair_reports == []
        assert ui.finished == 1
    finally:
        blocker_release.set()
        controller.close()
        scope.close()
        runtime.shutdown(wait=True)
