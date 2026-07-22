from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.services.backup_service import BackupService
from app.services.execution_runtime import ExecutionRuntime
from app.ui.views.backup_center import BackupCenterView
from app.services.world_write_coordinator import WorldWriteCoordinator


def _app(service: BackupService) -> Any:
    runtime = ExecutionRuntime()
    return SimpleNamespace(
        services=SimpleNamespace(backup=service),
        translate=lambda key, default: default,
        execution_runtime=runtime,
    )


def test_backup_center_tracks_selected_world_and_renders_records(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    service = BackupService(WorldWriteCoordinator())
    service.create_backup(world, "测试恢复点")
    view = BackupCenterView(cast(Any, _app(service)))

    view.on_save_selected(str(world))

    assert view._world_path_field.value == str(world)
    assert view._summary.value == "共 1 个恢复点"
    assert len(view._backup_list.controls) == 1


def test_backup_center_keeps_creation_next_to_form() -> None:
    view = BackupCenterView(cast(Any, _app(BackupService(WorldWriteCoordinator()))))

    actions = view.get_top_actions()

    assert actions == []
