"""Map color schemes and region value labels.

v1 map display is presence-based: existing regions share one fill color.
Biome / structure helpers are reserved for later layers.
"""
from typing import Any, Dict, Tuple

# Existing region fill (Minecraft grass-like)
REGION_FILL_COLOR = "#4CAF50"
REGION_BORDER_COLOR = "#2E7D32"
EMPTY_REGION_COLOR = "#263426"
ORIGIN_COLOR = "#7CB34288"
BACKGROUND_COLOR = "#162016"
SELECTED_BORDER_COLOR = "#FFD54F"


def get_region_color(_size: int = 0, _stats: Dict[str, Any] | None = None) -> str:
    """Solid fill for an existing region cell (not size-weighted)."""
    return REGION_FILL_COLOR


# Backward-compatible names used by older call sites during the transition.
def get_activity_color(size: int, stats: Dict[str, Any]) -> str:
    return get_region_color(size, stats)


def get_biome_color(biome: str) -> str:
    """Biome mode color mapping (reserved for later layers)."""
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
    """Structure mode color mapping (reserved for later layers)."""
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


def get_region_value_label(
    display_mode: str,
    coord: Tuple[int, int],
    size: int,
    region_meta: Dict[str, Any],
    stats: Dict[str, Any],
) -> str:
    """Short label for info overlay (no activity-heat wording)."""
    if display_mode == "biome":
        return f"主要群系 {region_meta.get('dominant_biome', 'unknown')}"
    if display_mode == "structure":
        count = int(region_meta.get("structure_count", 0) or 0)
        if count <= 0:
            return "未发现结构"
        return f"{region_meta.get('dominant_structure', 'unknown')} 等 {count} 个结构引用"
    return f"r.{coord[0]}.{coord[1]}.mca"


def get_mode_title(display_mode: str) -> str:
    """Display mode title."""
    return {
        "activity": "区域地图",
        "biome": "主要群系",
        "structure": "生成结构",
    }.get(display_mode, "区域地图")
