from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from app.services.backup_service import BackupService
from app.ui.views.backup_center import BackupCenterView


def _app(service: BackupService) -> Any:
    return SimpleNamespace(
        services=SimpleNamespace(backup=service),
        translate=lambda key, default: default,
    )


def test_backup_center_tracks_selected_world_and_renders_records(tmp_path: Path) -> None:
    world = tmp_path / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"level")
    service = BackupService()
    service.create_backup(world, "测试恢复点")
    view = BackupCenterView(cast(Any, _app(service)))

    view.on_save_selected(str(world))

    assert view._world_path_field.value == str(world)
    assert view._summary.value == "共 1 个恢复点"
    assert len(view._backup_list.controls) == 1


def test_backup_center_exposes_create_top_action() -> None:
    view = BackupCenterView(cast(Any, _app(BackupService())))

    actions = view.get_top_actions()

    assert len(actions) == 1
    assert actions[0].label == "创建备份"
