from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.ui.views.explorer.world_info_tab import WorldInfoTabMixin


class _ImmediateThread:
    def __init__(self, target, daemon: bool) -> None:
        del daemon
        self._target = target

    def start(self) -> None:
        self._target()


def test_explorer_quick_backup_uses_managed_backup_service(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    class BackupService:
        def create_backup(self, world_path, label, progress_callback):
            calls.append((world_path, label, progress_callback))
            return SimpleNamespace(backup_path=tmp_path / "backup")

    host = WorldInfoTabMixin()
    host.world_session = cast(Any, SimpleNamespace(world_path=tmp_path / "world"))
    host.app = cast(Any, SimpleNamespace(
        page=None,
        services=SimpleNamespace(backup=BackupService()),
        show_progress=lambda message: None,
        update_progress_with_task=lambda message, value: None,
        info_dialog=lambda title, message: None,
        handle_exception=lambda error, title: None,
        hide_progress=lambda: None,
    ))
    monkeypatch.setattr(
        "app.ui.views.explorer.world_info_tab.threading.Thread",
        _ImmediateThread,
    )

    host._create_backup()

    assert calls[0][0] == tmp_path / "world"
    assert calls[0][1] == "Explorer 快速备份"


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
