"""Build a Flet-independent presentation model for world information."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Callable, List, Mapping, Optional

from core.omni.models import ModInfo, WorldInfo


@dataclass(frozen=True)
class InfoRow:
    label: str
    value: str


@dataclass(frozen=True)
class InfoSection:
    title: str
    rows: tuple[InfoRow, ...]


Translate = Callable[..., str]


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
    translate: Optional[Translate] = None,
) -> List[InfoSection]:
    sections = [
        _basic_section(world_info, translate),
        _generation_section(world_info, translate),
        _time_section(world_info),
        _stats_section(stats),
        _data_pack_section(world_info),
        _mod_section(world_info, translate),
        _world_border_section(world_info, translate),
        _other_section(world_info),
    ]
    return [section for section in sections if section.rows]


def _section(title: str, rows: List[InfoRow]) -> InfoSection:
    return InfoSection(title, tuple(rows))


def _basic_section(info: WorldInfo, translate: Optional[Translate]) -> InfoSection:
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
    _append_bool(rows, "💀 极限模式", info.hardcore, translate)
    _append_bool(rows, "⌨️ 允许命令", info.allow_commands, translate)
    _append_bool(
        rows,
        _tr(translate, "world_info.difficulty_locked", "🔒 难度已锁定"),
        info.difficulty_locked,
        translate,
    )
    _append_bool(rows, "✅ 已初始化", info.initialized, translate)
    return _section("📋 基本信息", rows)


def _append_bool(
    rows: List[InfoRow],
    label: str,
    value: Optional[bool],
    translate: Optional[Translate] = None,
) -> None:
    if value is not None:
        rows.append(InfoRow(
            label,
            _tr(translate, "world_info.yes", "是")
            if value else _tr(translate, "world_info.no", "否"),
        ))


def _generation_section(
    info: WorldInfo,
    translate: Optional[Translate],
) -> InfoSection:
    rows: List[InfoRow] = []
    if info.seed is not None:
        rows.append(InfoRow("🌱 世界种子", str(info.seed)))
    if info.spawn_x is not None:
        rows.append(InfoRow(
            "📍 出生点",
            f"X: {info.spawn_x}  Y: {info.spawn_y}  Z: {info.spawn_z}",
        ))
    if info.spawn_angle is not None:
        rows.append(InfoRow(
            _tr(translate, "world_info.spawn_angle", "🧭 出生朝向"),
            f"{float(info.spawn_angle):g}°",
        ))
    _append_bool(
        rows,
        _tr(translate, "world_info.generate_features", "🏛️ 生成结构"),
        info.generate_features,
        translate,
    )
    _append_bool(
        rows,
        _tr(translate, "world_info.bonus_chest", "🎁 奖励箱"),
        info.bonus_chest,
        translate,
    )
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


def _mod_section(
    info: WorldInfo,
    translate: Optional[Translate],
) -> InfoSection:
    rows: List[InfoRow] = []
    mods = info.mods or []
    loaders = info.mod_loaders or []

    if mods:
        if info.mod_list_complete:
            status = _tr(
                translate,
                "world_info.mods_status_recorded",
                "是（存档记录了 {count} 个模组）",
                count=len(mods),
            )
        else:
            status = _tr(
                translate,
                "world_info.mods_status_inferred",
                "是（至少检测到 {count} 个，列表可能不完整）",
                count=len(mods),
            )
    elif loaders:
        status = _tr(
            translate,
            "world_info.mods_status_loader_only",
            "检测到模组加载器，但存档未保存可读取的模组清单",
        )
    elif info.was_modded is not None and bool(info.was_modded):
        status = _tr(
            translate,
            "world_info.mods_status_no_list",
            "是（存档未保存可读取的模组清单）",
        )
    elif info.was_modded is not None:
        status = _tr(
            translate,
            "world_info.mods_status_clean",
            "否（未检测到模组）",
        )
    else:
        status = _tr(
            translate,
            "world_info.mods_status_unknown",
            "未知（存档未提供模组标记）",
        )

    rows.append(InfoRow(
        _tr(translate, "world_info.mods_status", "🧩 是否使用模组"),
        status,
    ))
    if loaders:
        rows.append(InfoRow(
            _tr(translate, "world_info.mod_loaders", "⚙️ 模组加载器"),
            ", ".join(loaders),
        ))
    if mods:
        rows.append(InfoRow(
            _tr(translate, "world_info.mod_list", "📚 模组列表"),
            "\n".join(_format_mod(mod) for mod in mods),
        ))
        source = (
            _tr(
                translate,
                "world_info.mod_source_explicit",
                "level.dat 中的显式模组清单",
            )
            if info.mod_list_complete
            else _tr(
                translate,
                "world_info.mod_source_inferred",
                "根据存档数据包标识推断，可能不完整",
            )
        )
        rows.append(InfoRow(
            _tr(translate, "world_info.mod_source", "ℹ️ 清单来源"),
            source,
        ))
    return _section(
        _tr(translate, "world_info.mods_section", "🧩 模组信息"),
        rows,
    )


def _format_mod(mod: ModInfo) -> str:
    label = mod.mod_id
    if mod.name and mod.name.casefold() != mod.mod_id.casefold():
        label = f"{mod.name} ({mod.mod_id})"
    if mod.version:
        label += f" · {mod.version}"
    return label


def _world_border_section(
    info: WorldInfo,
    translate: Optional[Translate],
) -> InfoSection:
    rows: List[InfoRow] = []
    if info.border_center_x is not None and info.border_center_z is not None:
        rows.append(InfoRow(
            _tr(translate, "world_info.border_center", "🎯 中心坐标"),
            f"X: {_format_number(info.border_center_x)}  "
            f"Z: {_format_number(info.border_center_z)}",
        ))
    if info.border_size is not None:
        rows.append(InfoRow(
            _tr(translate, "world_info.border_size", "↔️ 边界直径"),
            _format_number(info.border_size),
        ))
    if info.border_warning_blocks is not None:
        rows.append(InfoRow(
            _tr(translate, "world_info.border_warning", "⚠️ 警告距离"),
            _tr(
                translate,
                "world_info.blocks",
                "{count} 格",
                count=int(info.border_warning_blocks),
            ),
        ))
    return _section(
        _tr(translate, "world_info.border_section", "🧱 世界边界"),
        rows,
    )


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _tr(
    translate: Optional[Translate],
    key: str,
    default: str,
    **kwargs: object,
) -> str:
    if translate is not None:
        return translate(key, default, **kwargs)
    return default.format(**kwargs)


def _other_section(info: WorldInfo) -> InfoSection:
    rows: List[InfoRow] = []
    if info.server_brands:
        rows.append(InfoRow(
            "🖥️ 服务器品牌",
            ", ".join(str(brand) for brand in info.server_brands),
        ))
    return _section("🔧 其他", rows)
