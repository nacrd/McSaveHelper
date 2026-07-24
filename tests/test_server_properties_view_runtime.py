"""Server properties view execution-runtime lifecycle tests."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.services.execution_runtime import ExecutionRuntime, LaneLimits
from app.services.server_properties_service import DEFAULT_SERVER_PROPERTIES
from app.ui.views import server_properties as server_properties_module
from app.ui.views.server_properties import ServerPropertiesView


class _BlockingServerPropertiesService:
    """Record load/save calls while allowing deterministic completion."""

    def __init__(self) -> None:
        self.load_started = threading.Event()
        self.load_release = threading.Event()
        self.save_started = threading.Event()
        self.save_release = threading.Event()
        self.load_thread = ""
        self.save_thread = ""
        self.saved: tuple[Path, dict[str, str]] | None = None

    def load(self, target: Path) -> dict[str, str]:
        del target
        self.load_thread = threading.current_thread().name
        self.load_started.set()
        if not self.load_release.wait(2):
            raise TimeoutError("读取测试未获准继续")
        props = DEFAULT_SERVER_PROPERTIES.copy()
        props["motd"] = "Loaded asynchronously"
        return props

    def save(self, target: Path, props: dict[str, str]) -> None:
        self.save_thread = threading.current_thread().name
        self.saved = (target, props.copy())
        self.save_started.set()
        if not self.save_release.wait(2):
            raise TimeoutError("保存测试未获准继续")


def _runtime() -> ExecutionRuntime:
    limits = LaneLimits(max_workers=1, queue_capacity=4)
    return ExecutionRuntime(io_limits=limits, cpu_limits=limits)


def _app(
    runtime: ExecutionRuntime,
    info_messages: list[tuple[str, str]],
    errors: list[tuple[Exception, str | None]],
) -> Any:
    return SimpleNamespace(
        execution_runtime=runtime,
        page=object(),
        log=lambda message, level="INFO": None,
        translate=lambda key, default="": default,
        pick_directory=lambda: None,
        info_dialog=lambda title, message: info_messages.append((title, message)),
        warn_dialog=lambda title, message: None,
        handle_exception=lambda error, title=None: errors.append((error, title)),
    )


def test_load_and_save_run_in_io_scope_with_busy_state(monkeypatch) -> None:
    runtime = _runtime()
    service = _BlockingServerPropertiesService()
    info_messages: list[tuple[str, str]] = []
    errors: list[tuple[Exception, str | None]] = []
    monkeypatch.setattr(
        server_properties_module,
        "get_server_properties_service",
        lambda log: service,
    )
    view = ServerPropertiesView(
        cast(Any, _app(runtime, info_messages, errors))
    )
    load_applied = threading.Event()
    save_applied = threading.Event()
    ui_callbacks: list[str] = []

    def run_on_ui(page: object, callback: Any, *args: object) -> None:
        del page
        ui_callbacks.append(callback.__name__)
        callback(*args)
        if callback.__name__ == "_apply_load_success":
            load_applied.set()
        if callback.__name__ == "_apply_save_success":
            save_applied.set()

    monkeypatch.setattr(server_properties_module, "run_on_ui", run_on_ui)
    main_thread = threading.current_thread().name
    target = Path("C:/server")

    try:
        view._path_field.value = str(target)
        view._load(cast(Any, None))

        assert service.load_started.wait(2)
        assert view._busy
        assert view._path_field.disabled
        assert view._browse_button.disabled
        assert view._save_button.disabled

        view._save(cast(Any, None))
        assert not service.save_started.is_set()

        service.load_release.set()
        assert load_applied.wait(2)
        assert not view._busy
        assert (
            getattr(view._fields["motd"], "value", None)
            == "Loaded asynchronously"
        )

        setattr(view._fields["motd"], "value", "Saved asynchronously")
        view._save(cast(Any, None))
        assert service.save_started.wait(2)
        assert view._busy
        service.save_release.set()
        assert save_applied.wait(2)

        assert service.saved is not None
        assert service.saved[0] == target
        assert service.saved[1]["motd"] == "Saved asynchronously"
        assert service.load_thread != main_thread
        assert service.save_thread != main_thread
        assert ui_callbacks == ["_apply_load_success", "_apply_save_success"]
        assert len(info_messages) == 2
        assert errors == []
    finally:
        service.load_release.set()
        service.save_release.set()
        view.dispose()
        runtime.shutdown(wait=True)


def test_dispose_cancels_load_and_drops_late_result(monkeypatch) -> None:
    runtime = _runtime()
    service = _BlockingServerPropertiesService()
    info_messages: list[tuple[str, str]] = []
    errors: list[tuple[Exception, str | None]] = []
    ui_callbacks: list[str] = []
    monkeypatch.setattr(
        server_properties_module,
        "get_server_properties_service",
        lambda log: service,
    )
    monkeypatch.setattr(
        server_properties_module,
        "run_on_ui",
        lambda page, callback, *args: ui_callbacks.append(callback.__name__),
    )
    view = ServerPropertiesView(
        cast(Any, _app(runtime, info_messages, errors))
    )

    try:
        view._path_field.value = "C:/server"
        view._load(cast(Any, None))
        assert service.load_started.wait(2)

        view.dispose()
        view.dispose()
        assert view._task_scope.is_closed
        assert not view._busy

        service.load_release.set()
        runtime.shutdown(wait=True)

        assert (
            getattr(view._fields["motd"], "value", None)
            == "A Minecraft Server"
        )
        assert info_messages == []
        assert errors == []
        assert ui_callbacks == []
    finally:
        service.load_release.set()
        runtime.shutdown(wait=True)
