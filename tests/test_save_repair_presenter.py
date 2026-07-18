from app.presenters.save_repair_presenter import (
    format_detect_report,
    format_repair_report,
)
from app.services.save_repair.models import DetectReport, RepairReport, WorldInfo


def test_format_detect_report_splits_world_info_and_result() -> None:
    report = DetectReport(
        world_info=WorldInfo(
            world_name="Test",
            version_name="1.21",
            data_version=3953,
            spawn_pos=(1, 64, -2),
            dimensions=["overworld", "nether"],
        ),
        chunks_checked=5,
        chunks_damaged=1,
        level_dat_ok=False,
        level_dat_issues=["缺少字段"],
        elapsed_seconds=1.25,
    )

    text = format_detect_report(report)

    assert "名称: Test" in text.world_info
    assert "出生点: (1, 64, -2)" in text.world_info
    assert "区块: 5 检查 / 1 损坏" in text.result
    assert "发现异常" in text.result


def test_format_repair_report_includes_backup_and_fixed_fields() -> None:
    report = RepairReport(
        chunks_checked=4,
        players_checked=2,
        players_fixed=1,
        level_dat_fixed=True,
        level_dat_repaired_fields=["DataVersion"],
        backup_path="backup",
        elapsed_seconds=2.0,
    )

    text = format_repair_report(report)

    assert "玩家修复: 1" in text
    assert "level.dat: 已修复 (DataVersion)" in text
    assert "备份: backup" in text
