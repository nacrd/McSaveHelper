"""Presentation formatting for save detection and repair reports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.services.save_repair_service import DetectReport, RepairReport


@dataclass(frozen=True)
class DetectReportText:
    world_info: str
    result: str


def format_detect_report(report: DetectReport) -> DetectReportText:
    """Format a detect report into the two text panels used by the UI."""
    info = report.world_info
    info_lines: List[str] = []
    if info.world_name:
        info_lines.append(f"名称: {info.world_name}")
    if info.version_name:
        info_lines.append(
            f"版本: {info.version_name} (DataVersion {info.data_version})"
        )
    if info.game_type_name:
        info_lines.append(f"模式: {info.game_type_name}")
    info_lines.append(f"难度: {info.difficulty_name}")
    info_lines.append(f"种子: {info.seed}")
    info_lines.append(
        f"出生点: ({info.spawn_pos[0]}, {info.spawn_pos[1]}, {info.spawn_pos[2]})"
    )
    if info.play_time_ticks > 0:
        hours = info.play_time_ticks / 72000
        info_lines.append(f"游戏时间: {hours:.1f} 小时")
    info_lines.append(
        f"存档大小: {info.world_size_mb:.1f} MB ({info.total_files} 文件)"
    )
    dimensions = ", ".join(info.dimensions) if info.dimensions else "无"
    info_lines.append(f"维度: {dimensions}")
    info_lines.append(
        f"区域文件: {info.region_count}  区块: ~{info.total_chunks}"
    )
    info_lines.append(f"玩家数量: {info.player_count}")

    result_lines: List[str] = []
    if report.cancelled:
        result_lines.append("(操作已取消)\n")
    result_lines.append(
        f"区块: {report.chunks_checked} 检查 / {report.chunks_damaged} 损坏"
    )
    if report.unreadable_regions:
        result_lines.append(
            f"无法读取的区域文件: {len(report.unreadable_regions)}"
        )
        result_lines.extend(f"  {name}" for name in report.unreadable_regions[:10])
        if len(report.unreadable_regions) > 10:
            result_lines.append(
                f"  ... 共 {len(report.unreadable_regions)} 个"
            )
    result_lines.append(
        f"玩家: {report.players_checked} 检查 / "
        f"{report.players_with_issues} 有问题"
    )
    for player_name, issues in list(report.player_issues.items())[:5]:
        result_lines.append(f"  {player_name}: {', '.join(issues)}")
    if len(report.player_issues) > 5:
        result_lines.append(f"  ... 共 {len(report.player_issues)} 个玩家")

    level_status = "正常" if report.level_dat_ok else "异常"
    result_lines.append(f"level.dat: {level_status}")
    result_lines.extend(f"  {issue}" for issue in report.level_dat_issues)
    result_lines.append(f"\n耗时: {report.elapsed_seconds:.1f}s")
    result_lines.append(
        "\n发现异常，建议执行修复。"
        if report.has_problems
        else "\n存档状态良好，未发现问题。"
    )
    return DetectReportText(
        world_info="\n".join(info_lines),
        result="\n".join(result_lines),
    )


def format_repair_report(report: RepairReport) -> str:
    """Format a repair report for the repair result panel."""
    lines: List[str] = []
    if report.cancelled:
        lines.append("(操作已取消)\n")
    elif not report.success:
        lines.append("(修复未完成)\n")
    lines.append(f"区块检查: {report.chunks_checked}")
    if report.chunks_damaged > 0:
        lines.append(f"区块损坏: {report.chunks_damaged}")
    if report.chunks_quarantined_regions > 0:
        lines.append(f"区域文件隔离: {report.chunks_quarantined_regions}")
    lines.append(f"玩家检查: {report.players_checked}")
    if report.players_fixed > 0:
        lines.append(f"玩家修复: {report.players_fixed}")
    if report.players_quarantined > 0:
        lines.append(f"玩家隔离: {report.players_quarantined}")

    level_status = "正常"
    if report.level_dat_fixed:
        level_status = "已修复"
        if report.level_dat_repaired_fields:
            fields = ", ".join(report.level_dat_repaired_fields)
            level_status += f" ({fields})"
    lines.append(f"level.dat: {level_status}")
    if report.backup_path:
        lines.append(f"\n备份: {report.backup_path}")
    lines.append(f"\n耗时: {report.elapsed_seconds:.1f}s")
    return "\n".join(lines)
