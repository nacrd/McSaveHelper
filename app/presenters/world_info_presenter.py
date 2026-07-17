"""Build a Flet-independent presentation model for world information."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import List, Mapping, Optional

from core.omni.models import WorldInfo


@dataclass(frozen=True)
class InfoRow:
    label: str
    value: str


@dataclass(frozen=True)
class InfoSection:
    title: str
    rows: tuple[InfoRow, ...]


GAME_TYPE_NAMES = {
    0: "生存模式",
    1: "创造模式",
    2: "冒险模式",
    3: "旁观模式",
}
DIFFICULTY_NAMES = {0: "和平", 1: "简单", 2: "普通", 3: "困难"}


def build_world_info_sections(
    world_info: WorldInfo,
    stats: Optional[Mapping[str, object]] = None,
) -> List[InfoSection]:
    sections = [
        _basic_section(world_info),
        _generation_section(world_info),
        _time_section(world_info),
        _stats_section(stats),
        _data_pack_section(world_info),
        _other_section(world_info),
    ]
    return [section for section in sections if section.rows]


def _section(title: str, rows: List[InfoRow]) -> InfoSection:
    return InfoSection(title, tuple(rows))


def _basic_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.level_name:
        rows.append(InfoRow("🏷️ 存档名称", info.level_name))
    if info.version_name:
        version = info.version_name
        if info.version_snapshot:
            version += "（快照）"
        if info.version_series:
            version += f" | 系列: {info.version_series}"
        rows.append(InfoRow("📦 游戏版本", f"{version}（ID: {info.version}）"))
    elif info.version:
        rows.append(InfoRow("📦 游戏版本 ID", str(info.version)))

    if info.game_type is not None and info.game_type in GAME_TYPE_NAMES:
        rows.append(InfoRow("🎮 游戏模式", GAME_TYPE_NAMES[info.game_type]))
    if info.difficulty is not None and info.difficulty in DIFFICULTY_NAMES:
        rows.append(InfoRow("⚔️ 难度", DIFFICULTY_NAMES[info.difficulty]))
    _append_bool(rows, "💀 极限模式", info.hardcore)
    _append_bool(rows, "⌨️ 允许命令", info.allow_commands)
    _append_bool(rows, "🔧 使用过模组", info.was_modded)
    _append_bool(rows, "✅ 已初始化", info.initialized)
    return _section("📋 基本信息", rows)


def _append_bool(rows: List[InfoRow], label: str, value: Optional[bool]) -> None:
    if value is not None:
        rows.append(InfoRow(label, "是" if value else "否"))


def _generation_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.seed is not None:
        rows.append(InfoRow("🌱 世界种子", str(info.seed)))
    if info.spawn_x is not None:
        rows.append(InfoRow(
            "📍 出生点",
            f"X: {info.spawn_x}  Y: {info.spawn_y}  Z: {info.spawn_z}",
        ))
    return _section("🌍 世界生成", rows)


def _time_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.last_played:
        rows.append(InfoRow("🕐 最后游玩", _format_last_played(info.last_played)))
    if info.time is not None:
        ticks = int(info.time)
        rows.append(InfoRow("⏱️ 总游戏时间", f"{ticks} 刻（约 {ticks // 24000} 天）"))
    if info.day_time is not None:
        day_ticks = int(info.day_time) % 24000
        rows.append(InfoRow(
            "🌞 当前时段",
            f"{_time_of_day(day_ticks)}（{day_ticks} 刻）",
        ))
    if info.raining is not None:
        rows.append(InfoRow("🌧️ 正在下雨", "🌧️ 是" if info.raining else "☀️ 否"))
    if info.thundering is not None:
        rows.append(InfoRow(
            "⛈️ 正在雷暴",
            "⛈️ 是" if info.thundering else "☀️ 否",
        ))
    return _section("⏰ 时间与天气", rows)


def _format_last_played(timestamp_ms: int) -> str:
    try:
        value = datetime.datetime.fromtimestamp(timestamp_ms / 1000)
        return value.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(timestamp_ms)


def _time_of_day(ticks: int) -> str:
    if ticks < 6000:
        return "☀️ 白天"
    if ticks < 12000:
        return "🌅 日落"
    if ticks < 13000:
        return "🌙 夜晚"
    if ticks < 18000:
        return "🌙 深夜"
    if ticks < 23000:
        return "🌄 日出"
    return "☀️ 黎明"


def _stats_section(stats: Optional[Mapping[str, object]]) -> InfoSection:
    rows: List[InfoRow] = []
    if stats:
        world_path = stats.get("world_path")
        if world_path:
            rows.append(InfoRow("📂 存档路径", str(world_path)))
        rows.extend([
            InfoRow("👥 玩家数", str(stats.get("player_count", 0))),
            InfoRow("🧭 维度数", str(stats.get("dimension_count", 0))),
            InfoRow("🗺️ 区域文件数", str(stats.get("region_count", 0))),
        ])
    return _section("📊 统计信息", rows)


def _data_pack_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.data_packs:
        enabled = info.data_packs.get("enabled", [])
        disabled = info.data_packs.get("disabled", [])
        if enabled:
            rows.append(InfoRow("✅ 已启用", _format_limited_list(enabled)))
        if disabled:
            rows.append(InfoRow("❌ 已禁用", _format_limited_list(disabled)))
    return _section("📦 数据包", rows)


def _format_limited_list(values: List[str], limit: int = 10) -> str:
    suffix = "..." if len(values) > limit else ""
    return ", ".join(values[:limit]) + suffix


def _other_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.server_brands:
        rows.append(InfoRow(
            "🖥️ 服务器品牌",
            ", ".join(str(brand) for brand in info.server_brands),
        ))
    return _section("🔧 其他", rows)
