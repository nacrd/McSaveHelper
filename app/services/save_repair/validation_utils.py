"""Validation Utilities - 验证工具

提供区块、玩家数据、level.dat 的验证功能。
"""
from typing import Any, List, Dict

import nbtlib


def validate_chunk(chunk: Any) -> bool:
    """验证区块数据完整性

    检查:
    1. chunk.data 存在且为 Compound
    2. Level 字段存在
    3. Sections 列表存在且非空
    4. DataVersion 存在
    """
    try:
        data = getattr(chunk, "data", None)
        if data is None:
            return False
        if not isinstance(data, nbtlib.tag.Compound):
            return False

        # 检查 Level 或直接子字段 (1.18+ 扁平化)
        has_level = "Level" in data
        has_sections = "sections" in data or "Sections" in data
        has_data_version = "DataVersion" in data

        if not has_data_version and not has_level and not has_sections:
            return False

        # 如果有 Level 子结构，验证其完整性
        if has_level:
            level = data["Level"]
            if not isinstance(level, nbtlib.tag.Compound):
                return False
            sections = level.get("Sections") or level.get("sections")
            if sections is not None and len(sections) == 0:
                return False

        return True
    except Exception:
        return False


def validate_player_data(nbt_data: Any, required_fields: List[str]) -> List[str]:
    """验证玩家数据，返回问题列表

    Args:
        nbt_data: 玩家数据 NBT
        required_fields: 必需字段列表

    Returns:
        问题列表
    """
    issues: List[str] = []

    # 检查缺失字段
    missing = [f for f in required_fields if f not in nbt_data]
    if missing:
        issues.append(f"缺失字段: {', '.join(missing)}")

    # 检查 Health 值范围
    if "Health" in nbt_data:
        try:
            health = float(nbt_data["Health"])
            if health < 0 or health > 20:
                issues.append(f"Health 值异常: {health}")
        except (ValueError, TypeError):
            issues.append("Health 值类型错误")

    return issues


def validate_level_dat_data(data: Any, required_fields: Dict[str, Any]) -> List[str]:
    """验证 level.dat 数据，返回问题列表

    Args:
        data: level.dat 的 Data 字段
        required_fields: 必需字段及默认值字典

    Returns:
        问题列表
    """
    issues: List[str] = []

    # 检查必需字段
    missing_fields: List[str] = []
    for field_name, default_value in required_fields.items():
        if field_name not in data and default_value is not None:
            missing_fields.append(field_name)

    # 检查范围异常
    range_issues: List[str] = []
    for spawn_field in ("SpawnX", "SpawnY", "SpawnZ"):
        if spawn_field in data:
            try:
                val = int(data[spawn_field])
                if spawn_field == "SpawnY" and (val < -64 or val > 320):
                    range_issues.append(f"{spawn_field} 超出范围: {val}")
            except (ValueError, TypeError):
                range_issues.append(f"{spawn_field} 值类型错误")

    if "Difficulty" in data:
        try:
            val = int(data["Difficulty"])
            if val < 0 or val > 3:
                range_issues.append(f"Difficulty 超出范围: {val}")
        except (ValueError, TypeError):
            range_issues.append("Difficulty 值类型错误")

    issues = [
        *(f"缺失字段: {f}" for f in missing_fields),
        *range_issues,
    ]

    return issues
