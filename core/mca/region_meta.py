"""从区域文件采样生物群系/结构元数据的纯辅助函数。

损坏 MCA 时返回尽量空的汇总，避免地图 UI 因单文件失败而整体不可用。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Optional

from core.perf_timing import PerfTimer


def scan_region_meta(region_file: Path) -> Dict[str, Any]:
    """采样区域文件并汇总主导生物群系与结构。

    Args:
        region_file: ``r.X.Z.mca`` 路径。

    Returns:
        Dict[str, Any]: 含 chunk_count、dominant_biome、structures 等字段。
    """
    biomes: Counter[str] = Counter()
    structures: Counter[str] = Counter()
    structure_positions: list[Dict[str, Any]] = []
    chunk_count = 0
    with PerfTimer("heatmap._scan_region_meta"):
        try:
            from core.mca import NativeRegion

            with NativeRegion.from_file(region_file) as region:
                for cx, cz in _primary_sample_points():
                    chunk_count += _collect_region_chunk(
                        region, cx, cz, biomes, structures, structure_positions
                    )
                if not biomes and not structures:
                    chunk_count += _scan_fallback_chunks(
                        region, chunk_count, biomes, structures, structure_positions
                    )
        except (OSError, ValueError, TypeError, RuntimeError, KeyError):
            pass
        except Exception:
            # Damaged MCA: return empty-ish meta rather than fail the map UI.
            pass

    dominant_biome = biomes.most_common(1)[0][0] if biomes else "unknown"
    dominant_structure = (
        structures.most_common(1)[0][0] if structures else "none"
    )
    return {
        "chunk_count": chunk_count,
        "dominant_biome": dominant_biome,
        "biomes": dict(biomes.most_common(8)),
        "structure_count": sum(structures.values()),
        "dominant_structure": dominant_structure,
        "structures": dict(structures.most_common(8)),
        "structure_positions": structure_positions[:12],
    }


def _primary_sample_points() -> tuple[tuple[int, int], ...]:
    return ((0, 0), (0, 16), (16, 0), (16, 16), (8, 8), (8, 24), (24, 8), (24, 24))


def _collect_region_chunk(
    region: Any,
    chunk_x: int,
    chunk_z: int,
    biomes: Counter[str],
    structures: Counter[str],
    positions: list[Dict[str, Any]],
) -> int:
    try:
        chunk = region.get_chunk(chunk_x, chunk_z)
        if chunk is None or chunk.data is None:
            return 0
        collect_biomes(chunk.data, biomes)
        collect_structures(chunk.data, structures, positions)
        return 1
    except (OSError, ValueError, TypeError, RuntimeError, KeyError, AttributeError):
        return 0
    except Exception:
        return 0


def _scan_fallback_chunks(
    region: Any,
    initial_count: int,
    biomes: Counter[str],
    structures: Counter[str],
    positions: list[Dict[str, Any]],
) -> int:
    found = 0
    for chunk_x in range(0, 32, 4):
        for chunk_z in range(0, 32, 4):
            if initial_count + found >= 16:
                return found
            found += _collect_region_chunk(
                region, chunk_x, chunk_z, biomes, structures, positions
            )
    return found


def collect_biomes(data: Any, counter: Counter[str]) -> None:
    """从区块 NBT 收集生物群系名称计数。

    同时兼容 1.18+ section palette 与旧版根级 Biomes 数组。

    Args:
        data: 区块 NBT 根或 Level 复合标签。
        counter: 就地累加的名称计数器。
    """
    root = chunk_root(data)
    sections = first_key(root, "sections", "Sections")
    if is_sequence(sections):
        for section in iter_values(sections):
            biomes = first_key(section, "biomes", "Biomes")
            palette = (
                first_key(biomes, "palette", "Palette")
                if is_mapping(biomes)
                else None
            )
            if is_sequence(palette):
                for biome in list(iter_values(palette))[:16]:
                    name = tag_text(biome)
                    if name:
                        counter[name] += 1
    legacy_biomes = first_key(root, "Biomes", "biomes")
    if is_sequence(legacy_biomes):
        for biome in list(iter_values(legacy_biomes))[:64]:
            name = tag_text(biome)
            if name:
                counter[name] += 1


def collect_structures(
    data: Any,
    counter: Counter[str],
    positions: list[Dict[str, Any]],
) -> None:
    """从区块 NBT 收集结构 starts/references 与可选位置。

    Args:
        data: 区块 NBT 根。
        counter: 结构名计数。
        positions: 就地追加的结构位置字典列表。
    """
    root = chunk_root(data)
    structures = first_key(root, "structures", "Structures")
    starts = (
        first_key(structures, "starts", "Starts")
        if is_mapping(structures)
        else None
    )
    if is_mapping(starts):
        for name, value in items(starts):
            if str(name).lower() not in {"references", "starts"} and value is not None:
                counter[str(name)] += 1
                pos = extract_structure_position(str(name), value)
                if pos:
                    positions.append(pos)
    refs = (
        first_key(structures, "References", "references")
        if is_mapping(structures)
        else None
    )
    if is_mapping(refs):
        for name, value in items(refs):
            try:
                if len(value) > 0:
                    counter[str(name)] += 1
            except (TypeError, ValueError, AttributeError):
                counter[str(name)] += 1


def extract_structure_position(
    name: str,
    value: Any,
) -> Optional[Dict[str, Any]]:
    """从结构 start 条目提取近似方块位置。

    优先 BB 包围盒，其次 Children 的 BB，最后 ChunkX/ChunkZ。

    Args:
        name: 结构资源名。
        value: start 复合标签。

    Returns:
        Optional[Dict[str, Any]]: 含 name/block_x/block_z 等字段，或 None。
    """
    if not is_mapping(value):
        return None
    bb = first_key(value, "BB", "bb", "bounding_box")
    pos = position_from_bb(name, bb)
    if pos:
        return pos
    children = first_key(value, "Children", "children")
    if is_sequence(children):
        for child in iter_values(children):
            if not is_mapping(child):
                continue
            pos = position_from_bb(
                name,
                first_key(child, "BB", "bb", "bounding_box"),
            )
            if pos:
                return pos
    chunk_x = first_key(value, "ChunkX", "chunkX", "chunk_x")
    chunk_z = first_key(value, "ChunkZ", "chunkZ", "chunk_z")
    if chunk_x is not None and chunk_z is not None:
        try:
            bx = int(tag_value(chunk_x)) * 16
            bz = int(tag_value(chunk_z)) * 16
            return {
                "name": name,
                "block_x": bx,
                "block_z": bz,
                "source": "chunk",
            }
        except (TypeError, ValueError):
            return None
    return None


def position_from_bb(name: str, bb: Any) -> Optional[Dict[str, Any]]:
    """从 6 元组包围盒取最小角作为结构标记点。

    Args:
        name: 结构名。
        bb: BB 标签或序列。

    Returns:
        Optional[Dict[str, Any]]: 含 block_x/y/z 与 source=bb，或 None。
    """
    raw = tag_value(bb)
    if is_sequence(raw):
        raw = list(iter_values(raw))
    if not isinstance(raw, list) or len(raw) < 6:
        return None
    try:
        return {
            "name": name,
            "block_x": int(tag_value(raw[0])),
            "block_y": int(tag_value(raw[1])),
            "block_z": int(tag_value(raw[2])),
            "source": "bb",
        }
    except (TypeError, ValueError):
        return None


def chunk_root(data: Any) -> Any:
    """返回实际数据根：旧版 ``Level`` 或扁平根。

    Args:
        data: 区块 NBT。

    Returns:
        Any: 用于字段查找的根映射。
    """
    level = first_key(data, "Level")
    if is_mapping(level):
        return level
    return data


def first_key(data: Any, *keys: str) -> Any:
    """在映射上按候选键名依次查找首个非 None 值。

    Args:
        data: 映射类 NBT。
        *keys: 大小写/命名兼容的候选键。

    Returns:
        Any: 首个命中值，或 None。
    """
    if not is_mapping(data):
        return None
    for key in keys:
        value = mapping_get(data, key)
        if value is not None:
            return value
    return None


def is_mapping(value: Any) -> bool:
    """判断值是否像键值映射（含 Compound）。"""
    raw = tag_value(value)
    return (
        isinstance(raw, dict)
        or hasattr(raw, "get")
        or hasattr(raw, "items")
    )


def is_sequence(value: Any) -> bool:
    """判断值是否像非字符串序列。"""
    raw = tag_value(value)
    if isinstance(raw, (str, bytes, dict)):
        return False
    return isinstance(raw, (list, tuple)) or hasattr(raw, "__iter__")


def mapping_get(data: Any, key: str) -> Any:
    """安全读取映射键；失败返回 None。"""
    raw = tag_value(data)
    try:
        if hasattr(raw, "get"):
            return raw.get(key)
        return raw[key]
    except (TypeError, KeyError, AttributeError, IndexError):
        return None


def items(data: Any) -> list[tuple[Any, Any]]:
    """物化映射的 items 列表；不可迭代时返回空列表。"""
    raw = tag_value(data)
    try:
        if hasattr(raw, "items"):
            return list(raw.items())
    except (TypeError, AttributeError):
        pass
    return []


def iter_values(data: Any) -> list[Any]:
    """将序列类 NBT 物化为列表。"""
    raw = tag_value(data)
    try:
        return list(raw)
    except (TypeError, ValueError):
        return []


def tag_text(value: Any) -> str:
    """将 NBT 节点尽力转为文本（生物群系/结构名）。"""
    raw = getattr(value, "value", value)
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        return raw
    if hasattr(value, "value") and raw is not None:
        return str(raw)
    return str(raw) if raw is not None else ""


def tag_value(value: Any) -> Any:
    """解包 NBT 标签的 .value，已是纯 Python 则原样返回。"""
    return getattr(value, "value", value)
