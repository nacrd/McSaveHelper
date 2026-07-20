"""Validation Utilities - 验证工具

提供区块、玩家数据、level.dat 的验证功能。
"""
import time
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Tuple

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


def _missing_level_fields(
    data: Any,
    required_fields: Mapping[str, Any],
) -> List[str]:
    return [
        field_name
        for field_name, default_value in required_fields.items()
        if field_name not in data and default_value is not None
    ]


def _integer_range_issue(
    data: Any,
    field_name: str,
    bounds: Optional[Tuple[int, int]],
) -> Optional[str]:
    if field_name not in data:
        return None
    try:
        value = int(data[field_name])
    except (ValueError, TypeError):
        return f"{field_name} 值类型错误"
    if bounds is not None and not bounds[0] <= value <= bounds[1]:
        return f"{field_name} 超出范围: {value}"
    return None


def _level_range_issues(data: Any) -> List[str]:
    rules = (
        ("SpawnX", None),
        ("SpawnY", (-64, 320)),
        ("SpawnZ", None),
        ("Difficulty", (0, 3)),
    )
    issues: List[str] = []
    for field_name, bounds in rules:
        issue = _integer_range_issue(data, field_name, bounds)
        if issue is not None:
            issues.append(issue)
    return issues


def validate_level_dat_data(
    data: Any,
    required_fields: Mapping[str, Any],
) -> List[str]:
    """验证 level.dat 数据，返回问题列表

    Args:
        data: level.dat 的 Data 字段
        required_fields: 必需字段及默认值字典

    Returns:
        问题列表
    """
    missing_fields = _missing_level_fields(data, required_fields)
    return [
        *(f"缺失字段: {field_name}" for field_name in missing_fields),
        *_level_range_issues(data),
    ]


def quarantine_file(
    file_path: Path,
    log: Callable[[str, str], None],
) -> None:
    """Rename a damaged file to a ``.corrupted`` sibling for later inspection."""
    try:
        new_path = file_path.with_suffix(file_path.suffix + ".corrupted")
        if new_path.exists():
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            new_path = file_path.with_suffix(
                f"{file_path.suffix}.corrupted_{timestamp}"
            )
            log(f"已有隔离文件存在，使用新名称: {new_path.name}", "WARNING")
        file_path.rename(new_path)
        log(f"已隔离损坏文件: {file_path.name} -> {new_path.name}", "WARNING")
    except Exception as exc:
        log(f"无法隔离文件 {file_path.name}: {exc}", "ERROR")
