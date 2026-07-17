"""Migrator option constants and pure UI decision helpers."""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

VersionOption = Tuple[str, int, str]
PlatformOption = Tuple[str, str]

VERSION_OPTIONS: Sequence[VersionOption] = [
    ("1.21.4", 3953, '最新正式版'),
    ("1.21.0", 3952, ""),
    ("1.20.6", 3839, '数据组件重构'),
    ("1.20.4", 3700, ""),
    ("1.20.2", 3698, ""),
    ("1.20.0", 3692, ""),
    ("1.19.4", 3337, ""),
    ("1.19.2", 3120, ""),
    ("1.18.2", 2975, ""),
    ("1.17.1", 2730, ""),
    ("1.16.5", 2586, ""),
    ("1.12.2", 1343, '扁平化前'),
]

PLATFORM_OPTIONS: Sequence[PlatformOption] = [
    ("java", 'Java 版'),
    ("bedrock", '基岩版'),
]

# Data version threshold where large downgrades become risky.
RISKY_DOWNGRADE_VERSION = 2586


def format_version_label(name: str, version_id: int, note: str = "") -> str:
    """Build a dropdown label for a Minecraft data version."""
    suffix = f"  — {note}" if note else ""
    return f"{name} (ID: {version_id}){suffix}"


def mode_description(mode: str) -> str:
    """Return the human-readable description for a conversion mode."""
    if mode == "fast":
        return '⚡ 快速模式：仅复制UUID文件，速度最快'
    return '🧠 完整模式：深度 NBT 修补 + 版本转换 + 物品ID迁移'


def version_downgrade_warning(target_version: int) -> Optional[str]:
    """Return a warning message when the target data version is a large drop."""
    if target_version < RISKY_DOWNGRADE_VERSION:
        return (
            f"⚠️ 降到 ID {target_version} 是较大跨度，"
            + '部分新版本数据可能丢失。请确保已备份存档。'
        )
    return None


def format_uuid_query_result(
    name: str,
    offline_uuid: str,
    online_uuid: Optional[str] = None,
    official_name: Optional[str] = None,
) -> str:
    """Format UUID lookup output for the migrator result panel."""
    lines = [f"玩家: {name}", f"离线 UUID: {offline_uuid}"]
    if online_uuid:
        lines.append(f"正版 UUID: {online_uuid}")
        if official_name and official_name != name:
            lines.append(f"官方名称: {official_name}")
    else:
        lines.append('正版 UUID: 未获取到（可能为离线账号）')
    return chr(10).join(lines)
