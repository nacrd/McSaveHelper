from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, cast

from app.services.execution_runtime import CancellationToken, OperationScope
from app.ui.views.explorer.world_info_tab import WorldInfoTabMixin


class _ImmediateScope:
    def submit(self, operation, work, **kwargs) -> None:
        del operation, kwargs
        work(CancellationToken())


def test_explorer_quick_backup_uses_managed_backup_service(
    tmp_path: Path,
) -> None:
    calls = []

    class BackupService:
        def create_backup(
            self,
            world_path,
            label,
            progress_callback,
            cancel_check,
        ):
            calls.append((world_path, label, progress_callback, cancel_check))
            return SimpleNamespace(backup_path=tmp_path / "backup")

    host = WorldInfoTabMixin()
    host._task_scope = cast(OperationScope, _ImmediateScope())
    host.world_session = cast(Any, SimpleNamespace(world_path=tmp_path / "world"))
    host._world_load_generation = 1
    setattr(host, "_disposed", False)
    host.app = cast(Any, SimpleNamespace(
        page=None,
        backup=BackupService(),
        show_progress=lambda message: None,
        update_progress_with_task=lambda message, value: None,
        info_dialog=lambda title, message: None,
        handle_exception=lambda error, title: None,
        hide_progress=lambda: None,
    ))

    host._create_backup()

    assert calls[0][0] == tmp_path / "world"
    assert calls[0][1] == "Explorer 快速备份"
    assert calls[0][3]() is False


def test_explorer_quick_backup_drops_ui_after_world_switch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    queued: list[Callable[[], None]] = []
    events: list[object] = []

    def queue_ui(page, callback, *args, **kwargs) -> None:
        del page
        queued.append(lambda: callback(*args, **kwargs))

    monkeypatch.setattr(
        "app.ui.views.explorer.world_info_tab.run_on_ui",
        queue_ui,
    )

    class BackupService:
        def create_backup(
            self,
            world_path,
            label,
            progress_callback,
            cancel_check,
        ):
            del world_path, label
            assert cancel_check() is False
            progress_callback(0.5, "copying")
            return SimpleNamespace(backup_path=tmp_path / "backup")

    old_session = SimpleNamespace(world_path=tmp_path / "old")
    host = WorldInfoTabMixin()
    host._task_scope = cast(OperationScope, _ImmediateScope())
    host.world_session = cast(Any, old_session)
    host._world_load_generation = 1
    setattr(host, "_disposed", False)
    host.app = cast(Any, SimpleNamespace(
        page=object(),
        backup=BackupService(),
        show_progress=lambda message: events.append(("show", message)),
        update_progress_with_task=lambda message, value: events.append(
            ("progress", message, value)
        ),
        info_dialog=lambda title, message: events.append((title, message)),
        handle_exception=lambda error, title: events.append((title, error)),
        hide_progress=lambda: events.append("hide"),
    ))

    host._create_backup()
    assert queued
    host.world_session = cast(
        Any,
        SimpleNamespace(world_path=tmp_path / "new"),
    )
    host._world_load_generation += 1
    for callback in queued:
        callback()

    assert events == []


def test_explorer_restore_action_opens_backup_center(tmp_path: Path) -> None:
    switched = []
    host = WorldInfoTabMixin()
    host.world_session = cast(Any, SimpleNamespace(world_path=tmp_path / "world"))
    host.app = cast(Any, SimpleNamespace(
        view_manager=SimpleNamespace(
            switch_view=lambda view_id: switched.append(view_id)
        ),
    ))

    host._restore_backup()

    assert switched == ["backup_center"]
