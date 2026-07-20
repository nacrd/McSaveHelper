"""Validation Utilities - 验证工具

提供区块、玩家数据、level.dat 的验证功能。
"""
import time
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Tuple

import nbtlib


def validate_chunk(chunk: Any) -> bool:
    """验证区块数据完整性。

    检查 ``chunk.data`` 是否为 Compound，并确认至少具备
    ``DataVersion``、``Level`` 或扁平化 ``sections`` 之一；
    若存在 ``Level`` 子结构，则 Sections 不得为空列表。

    Args:
        chunk: 区域读取得到的区块对象（需暴露 ``data``）。

    Returns:
        bool: 结构可接受时为 True；损坏或异常访问时为 False。
    """
    try:
        data = getattr(chunk, "data", None)
        if data is None:
            return False
        if not isinstance(data, nbtlib.tag.Compound):
            return False

        # Level 或 1.18+ 扁平化 sections / DataVersion
        has_level = "Level" in data
        has_sections = "sections" in data or "Sections" in data
        has_data_version = "DataVersion" in data

        if not has_data_version and not has_level and not has_sections:
            return False

        if has_level:
            level = data["Level"]
            if not isinstance(level, nbtlib.tag.Compound):
                return False
            sections = level.get("Sections") or level.get("sections")
            if sections is not None and len(sections) == 0:
                return False

        return True
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def validate_player_data(nbt_data: Any, required_fields: List[str]) -> List[str]:
    """验证玩家数据，返回问题描述列表。

    Args:
        nbt_data: 玩家数据 NBT 根标签。
        required_fields: 必需字段名列表。

    Returns:
        list[str]: 问题描述；无问题时为空列表。
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
    """验证 ``level.dat`` 的 ``Data`` 字段，返回问题描述列表。

    Args:
        data: ``level.dat`` 的 ``Data`` Compound。
        required_fields: 必需字段映射（值可为默认值占位，非 None 表示必填）。

    Returns:
        list[str]: 缺失字段与范围问题描述。
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
    """将损坏文件重命名为同目录 ``.corrupted`` 旁路副本以便排查。

    Args:
        file_path: 待隔离文件路径。
        log: 日志回调 ``(message, level)``。
    """
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
    except OSError as exc:
        log(f"无法隔离文件 {file_path.name}: {exc}", "ERROR")


def iter_region_chunk_coordinates(region: Any):
    """Yield local chunk coords present in ``region`` (or a full 32x32 grid).

    Prefers ``region.iter_present_chunks()`` when available so empty slots are
    not scanned.
    """
    try:
        return region.iter_present_chunks()
    except AttributeError:
        return (
            (chunk_x, chunk_z)
            for chunk_x in range(32)
            for chunk_z in range(32)
        )


def count_damaged_chunks(
    region_file: Path,
    is_cancelled: Callable[[], bool],
    region_factory: Optional[Callable[[str], Any]] = None,
) -> Tuple[int, bool]:
    """统计单个区域文件中不可读或结构无效的区块数。

    Args:
        region_file: ``.mca`` 路径。
        is_cancelled: 返回 True 时中止扫描。
        region_factory: 可选区域打开工厂（测试注入）；默认使用
            :class:`core.mca.NativeRegion`。

    Returns:
        tuple[int, bool]: ``(damaged_count, completed)``。若中途取消，
        ``completed`` 为 False，并返回已累计的部分计数。
    """
    from core.mca import NativeRegion as Region

    open_region = region_factory or (lambda path: Region.from_file(path))
    damaged = 0
    with open_region(str(region_file)) as region:
        for chunk_x, chunk_z in iter_region_chunk_coordinates(region):
            if is_cancelled():
                return damaged, False
            try:
                chunk = region.get_chunk(chunk_x, chunk_z)
                if chunk is not None and not validate_chunk(chunk):
                    damaged += 1
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                damaged += 1
            except Exception:
                # 第三方/区域解析库的未知错误也计为损坏区块。
                damaged += 1
    return damaged, True
