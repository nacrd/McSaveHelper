"""Heatmap color schemes and region value labels."""
import math
from typing import Any, Dict, Tuple


def get_activity_color(size: int, stats: Dict[str, int]) -> str:
    """Activity mode color: cold blue → warm red."""
    if stats.get("min_size") == stats.get("max_size"):
        return "#64B5F6"
    min_size = max(1, stats.get("min_size", 1))
    max_size = stats.get("max_size", 2)
    try:
        log_min = math.log(min_size)
        log_max = math.log(max_size)
        log_size = math.log(max(1, size))
        ratio = (log_size - log_min) / (log_max - log_min) if log_max > log_min else 0.5
    except (ValueError, TypeError):
        ratio = 0.5
    ratio = max(0.0, min(1.0, ratio))
    if ratio < 0.18:
        return "#2E7D32"
    if ratio < 0.36:
        return "#689F38"
    if ratio < 0.56:
        return "#C0A44A"
    if ratio < 0.76:
        return "#D9822B"
    if ratio < 0.92:
        return "#C63D2F"
    return "#8E24AA"


def get_biome_color(biome: str) -> str:
    """Biome mode color mapping."""
    biome = biome.lower()
    if "ocean" in biome or "river" in biome:
        return "#1E88E5"
    if "desert" in biome or "badlands" in biome:
        return "#D6B44C"
    if "snow" in biome or "frozen" in biome or "ice" in biome:
        return "#B3E5FC"
    if "jungle" in biome:
        return "#2E7D32"
    if "forest" in biome or "taiga" in biome:
        return "#388E3C"
    if "swamp" in biome or "mangrove" in biome:
        return "#607D3B"
    if "nether" in biome or "basalt" in biome or "crimson" in biome or "warped" in biome:
        return "#8E2424"
    if "end" in biome:
        return "#C5B56D"
    if biome == "unknown":
        return "#455A64"
    return "#7CB342"


def get_structure_color(count: int, name: str) -> str:
    """Structure mode color mapping."""
    name = name.lower()
    if count <= 0 or name == "none":
        return "#455A64"
    if "village" in name:
        return "#FFD54F"
    if "mineshaft" in name:
        return "#8D6E63"
    if "stronghold" in name:
        return "#7E57C2"
    if "mansion" in name or "monument" in name:
        return "#26A69A"
    if "fortress" in name or "bastion" in name:
        return "#D84315"
    return "#FFB300" if count < 3 else "#FF7043"


def get_activity_name(size: int, stats: Dict[str, Any]) -> str:
    """Activity level name for display."""
    avg = stats.get("avg_size", 0) or 0
    if avg <= 0:
        return "未知活动度"
    ratio = size / avg
    if ratio >= 2.0:
        return "极高活动"
    if ratio >= 1.4:
        return "高活动"
    if ratio >= 0.8:
        return "普通活动"
    if ratio >= 0.35:
        return "低活动"
    return "很少生成"


def get_activity_icon(size: int, stats: Dict[str, Any]) -> str:
    """Activity level icon."""
    name = get_activity_name(size, stats)
    return {"极高活动": "◆◆", "高活动": "◆", "普通活动": "■", "低活动": "▪"}.get(name, "·")


def get_region_value_label(display_mode: str, coord: Tuple[int, int], size: int,
                           region_meta: Dict[str, Any], stats: Dict[str, Any]) -> str:
    """Region value label for info overlay."""
    if display_mode == "biome":
        return f"主要群系 {region_meta.get('dominant_biome', 'unknown')}"
    if display_mode == "structure":
        count = int(region_meta.get("structure_count", 0) or 0)
        if count <= 0:
            return "未发现结构"
        return f"{region_meta.get('dominant_structure', 'unknown')} 等 {count} 个结构引用"
    return get_activity_name(size, stats)


def get_mode_title(display_mode: str) -> str:
    """Display mode title."""
    return {"activity": "活动热力", "biome": "主要群系", "structure": "生成结构"}.get(display_mode, "区域视图")
