"""Backward-compatible re-export of map color schemes."""
from app.ui.views.explorer.map.color_schemes import (  # noqa: F401
    get_activity_color,
    get_activity_icon,
    get_activity_name,
    get_biome_color,
    get_mode_title,
    get_region_value_label,
    get_structure_color,
)

__all__ = [
    "get_activity_color",
    "get_activity_icon",
    "get_activity_name",
    "get_biome_color",
    "get_mode_title",
    "get_region_value_label",
    "get_structure_color",
]
