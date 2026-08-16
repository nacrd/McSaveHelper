"""迁移页面的纯显示决策。"""
from __future__ import annotations

from typing import Optional


RISKY_DOWNGRADE_VERSION = 2586


def mode_description(mode: str) -> str:
    """返回迁移模式说明。"""
    if mode == "fast":
        return "快速模式：仅复制 UUID 文件，速度最快"
    return "完整模式：深度 NBT 修补 + 版本转换 + 物品 ID 迁移"


def version_downgrade_warning(target_version: int) -> Optional[str]:
    """目标版本跨度较大时返回警告。"""
    if target_version >= RISKY_DOWNGRADE_VERSION:
        return None
    return (
        f"警告：降到 ID {target_version} 是较大跨度，"
        "部分新版本数据可能丢失。请确保已备份存档。"
    )


def format_uuid_query_result(
    name: str,
    offline_uuid: str,
    online_uuid: Optional[str] = None,
    official_name: Optional[str] = None,
) -> str:
    """格式化玩家 UUID 查询结果。"""
    lines = [f"玩家: {name}", f"离线 UUID: {offline_uuid}"]
    if online_uuid:
        lines.append(f"正版 UUID: {online_uuid}")
        if official_name and official_name != name:
            lines.append(f"官方名称: {official_name}")
    else:
        lines.append("正版 UUID: 未获取到（可能为离线账号）")
    return "\n".join(lines)
