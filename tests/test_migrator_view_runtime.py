"""Migrator view background UUID query lifecycle tests."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.application import Application
from app.models.config import MigrationConfig
from app.services.execution_runtime import (
    ExecutionLane,
    ExecutionRuntime,
    LaneLimits,
    OperationCancelledError,
)
from app.ui.views import migrator as migrator_module
from app.ui.views.migrator import MigratorView


class _BlockingUuidService:
    """Hold named online lookups until the test releases them."""

    def __init__(self) -> None:
        self.started = {
            "Steve": threading.Event(),
            "Alex": threading.Event(),
        }
        self.release = {
            "Steve": threading.Event(),
            "Alex": threading.Event(),
        }
        self.worker_threads: dict[str, str] = {}

    def generate_offline_uuid(self, name: str) -> str:
        return f"offline-{name}"

    def query_online_uuid(
        self,
        name: str,
        log_callback: object,
    ) -> tuple[str, str]:
        del log_callback
        self.worker_threads[name] = threading.current_thread().name
        self.started[name].set()
        if not self.release[name].wait(2):
            raise TimeoutError(f"UUID 查询未获准继续: {name}")
        return f"online-{name}", name


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=2, queue_capacity=4)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _app(runtime: ExecutionRuntime, uuid_service: object) -> Any:
    migration_commands = SimpleNamespace(
        start=lambda: None,
        cancel=lambda: False,
        choose_destination=lambda: None,
        choose_batch_directory=lambda: None,
        close=lambda: None,
    )
    return SimpleNamespace(
        config=SimpleNamespace(migration=MigrationConfig()),
        execution_runtime=runtime,
        migration=SimpleNamespace(scan_result="", scan_batch_dir=lambda path: []),
        migration_commands=migration_commands,
        uuid=uuid_service,
        page=object(),
        translate=lambda key, default="", **kwargs: default.format(**kwargs),
        log=lambda message, level="INFO": None,
        warn_dialog=lambda title, message: None,
        handle_exception=lambda error, title=None: None,
    )


def test_uuid_query_uses_io_lane_and_drops_cancelled_result(monkeypatch) -> None:
    runtime = _runtime()
    uuid_service = _BlockingUuidService()
    view = MigratorView(cast(Any, _app(runtime, uuid_service)))
    delivered = threading.Event()
    ui_callbacks: list[str] = []

    def run_on_ui(page: object, callback: Any, *args: object) -> None:
        del page
        ui_callbacks.append(callback.__name__)
        callback(*args)
        if callback.__name__ == "_apply_uuid_query_success":
            delivered.set()

    monkeypatch.setattr(migrator_module, "run_on_ui", run_on_ui)
    main_thread = threading.current_thread().name

    try:
        view._query_field.value = "Steve"
        view._query_uuid()
        first_handle = view._query_handle
        assert first_handle is not None
        assert first_handle.lane is ExecutionLane.IO
        assert uuid_service.started["Steve"].wait(2)

        view._query_field.value = "Alex"
        view._query_uuid()
        second_handle = view._query_handle
        assert second_handle is not None
        assert second_handle.lane is ExecutionLane.IO
        assert first_handle.cancel_requested
        assert uuid_service.started["Alex"].wait(2)

        uuid_service.release["Alex"].set()
        assert delivered.wait(2)
        assert "online-Alex" in str(view._query_result.value)

        uuid_service.release["Steve"].set()
        with pytest.raises(OperationCancelledError):
            first_handle.result(timeout=2)
        runtime.shutdown(wait=True)

        assert "online-Alex" in str(view._query_result.value)
        assert ui_callbacks == ["_apply_uuid_query_success"]
        assert uuid_service.worker_threads["Steve"] != main_thread
        assert uuid_service.worker_threads["Alex"] != main_thread
    finally:
        uuid_service.release["Steve"].set()
        uuid_service.release["Alex"].set()
        view.dispose()
        runtime.shutdown(wait=True)


def test_dispose_keeps_application_migration_commands_available() -> None:
    runtime = _runtime()
    starts: list[bool] = []
    closes: list[bool] = []
    app = _app(runtime, SimpleNamespace())
    app.migration_commands = SimpleNamespace(
        start=lambda: starts.append(True),
        cancel=lambda: False,
        choose_destination=lambda: None,
        choose_batch_directory=lambda: None,
        close=lambda: closes.append(True),
    )
    first = MigratorView(cast(Any, app))
    second: MigratorView | None = None

    try:
        first.dispose()

        assert closes == []

        second = MigratorView(cast(Any, app))
        second.get_top_actions()[0].handler(cast(Any, None))

        assert starts == [True]
        assert closes == []
    finally:
        first.dispose()
        if second is not None:
            second.dispose()
        runtime.shutdown(wait=True)


def test_application_dispose_closes_migration_after_view_failure() -> None:
    events: list[str] = []
    app = Application.__new__(Application)

    def fail_view_dispose() -> None:
        events.append("views")
        raise RuntimeError("view dispose failed")

    app.view_manager = SimpleNamespace(dispose=fail_view_dispose)
    app.migration_controller = SimpleNamespace(
        close=lambda: events.append("migration"),
    )

    with pytest.raises(RuntimeError, match="view dispose failed"):
        app._dispose_views_and_migration()

    assert events == ["views", "migration"]
