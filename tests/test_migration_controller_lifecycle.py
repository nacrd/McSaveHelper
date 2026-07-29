"""Deterministic migration controller lifecycle tests."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Callable
from typing import cast

from app.controllers.migration_controller import (
    MigrationController,
    MigrationControllerDependencies,
)
from app.services.config_service import ConfigService
from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.migration_service import MigrationService
from core.batch_processor import BatchCancelledError


class _QueuedUi:
    def __init__(self) -> None:
        self.callbacks: queue.Queue[Callable[[], None]] = queue.Queue()

    def post(self, callback: Callable[[], None]) -> None:
        self.callbacks.put(callback)

    def drain(self) -> None:
        while True:
            try:
                self.callbacks.get_nowait()()
            except queue.Empty:
                return


class _Migration:
    def __init__(self) -> None:
        self.batch_worlds: list[Path] = []
        self.started = threading.Event()
        self.second_started = threading.Event()
        self.release = threading.Event()
        self.cancel_calls = 0
        self.calls: list[dict[str, Any]] = []

    def run_single(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        self.started.set()
        if len(self.calls) == 2:
            self.second_started.set()
        kwargs["log_cb"](
            "old generation" if len(self.calls) == 1 else "new generation",
            "INFO",
        )
        while not self.release.wait(0.01):
            if kwargs["cancel_check"]():
                raise BatchCancelledError("cancelled")
        return "converted/world"

    def run_batch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {}

    def cancel_active(self) -> bool:
        self.cancel_calls += 1
        self.release.set()
        return True

    def open_folder(self, path: str) -> None:
        del path


def _build(
    tmp_path: Path,
    migration: _Migration,
    ui: _QueuedUi,
    runtime: ExecutionRuntime,
    state: dict[str, list[Any]],
) -> MigrationController:
    config = ConfigService(tmp_path / "config")
    config.migration.src_path = str(tmp_path / "source")
    config.migration.dest_path = str(tmp_path / "destination")

    def translate(key: str, default: str = "", **kwargs: Any) -> str:
        del key
        return default.format(**kwargs)

    def start_worker(operation: str, target: Any) -> Any:
        state.setdefault("workers", []).append(operation)
        return runtime.submit(operation, target)

    return MigrationController(
        MigrationControllerDependencies(
            config=config,
            migration=cast(MigrationService, migration),
            translate=translate,
            warn_dialog=lambda *args, **kwargs: state.setdefault(
                "warnings", []
            ).append((args, kwargs)),
            error_dialog=lambda *args, **kwargs: state.setdefault(
                "errors", []
            ).append((args, kwargs)),
            handle_exception=lambda *args, **kwargs: state.setdefault(
                "exceptions", []
            ).append((args, kwargs)),
            show_success=lambda *args: state.setdefault(
                "successes", []
            ).append(args),
            set_start_enabled=lambda value: state.setdefault(
                "enabled", []
            ).append(value),
            update_page=lambda: state.setdefault("updates", []).append(True),
            log=lambda *args: state.setdefault("logs", []).append(args),
            log_header=lambda value: state.setdefault("headers", []).append(
                value
            ),
            update_progress=lambda value: state.setdefault(
                "progress", []
            ).append(value),
            set_progress_label=lambda value: state.setdefault(
                "labels", []
            ).append(value),
            set_progress_value=lambda value: state.setdefault(
                "progress_values", []
            ).append(value),
            start_worker=start_worker,
            post_ui=ui.post,
        )
    )


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=2)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def test_duplicate_start_submits_only_one_worker(tmp_path: Path) -> None:
    runtime = _runtime()
    ui = _QueuedUi()
    migration = _Migration()
    state: dict[str, list[Any]] = {}
    controller = _build(tmp_path, migration, ui, runtime, state)
    try:
        controller.start()
        assert migration.started.wait(timeout=2)
        controller.start()

        assert state["workers"] == ["migration_single"]
        assert state["warnings"]

        assert controller.cancel() is True
        assert controller.cancel() is False
        migration.release.set()
        ui.drain()
        assert migration.cancel_calls == 1
        assert state.get("successes", []) == []
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_close_is_idempotent_and_drops_completion_ui(tmp_path: Path) -> None:
    runtime = _runtime()
    ui = _QueuedUi()
    migration = _Migration()
    state: dict[str, list[Any]] = {}
    controller = _build(tmp_path, migration, ui, runtime, state)
    try:
        controller.start()
        assert migration.started.wait(timeout=2)
        handle = controller._active_operation
        assert handle is not None
        completed = threading.Event()
        handle.add_done_callback(lambda _: completed.set())

        controller.close()
        controller.close()

        assert completed.wait(timeout=2)
        ui.drain()
        assert migration.cancel_calls == 1
        assert state.get("successes", []) == []
        assert state["enabled"] == [False]
    finally:
        controller.close()
        runtime.shutdown(wait=True)


def test_queued_old_generation_is_discarded_before_ui_drain(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    ui = _QueuedUi()
    migration = _Migration()
    state: dict[str, list[Any]] = {}
    controller = _build(tmp_path, migration, ui, runtime, state)
    try:
        controller.start()
        assert migration.started.wait(timeout=2)
        controller.cancel()
        migration.release.set()

        # The first handle is complete, but its finish callback is still in
        # the UI queue.  A new start must invalidate the old generation.
        first_handle = controller._active_operation
        assert first_handle is not None
        first_done = threading.Event()
        first_handle.add_done_callback(lambda _: first_done.set())
        assert first_done.wait(timeout=2)
        controller.start()
        assert migration.second_started.wait(timeout=2)
        migration.release.set()

        ui.drain()

        messages = [message for message, _ in state.get("logs", [])]
        assert "old generation" not in messages
        assert "new generation" in messages
    finally:
        controller.close()
        migration.release.set()
        runtime.shutdown(wait=True)
