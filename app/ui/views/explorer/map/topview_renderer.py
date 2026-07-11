"""Top-down (bird's-eye) region tile renderer for the map display.

Renders one r.x.z.mca region into a small PNG suitable for Canvas tiles.
Uses native core.mca (heightmap + palette) instead of anvil-parser.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False

# Progressive tile ladder (pixels per region edge).
# 16 -> fast first paint; 32 overview; 64 region focus; 128 chunk inspection.
PREVIEW_TILE_SIZE = 16
DEFAULT_TILE_SIZE = 32
DETAIL_TILE_SIZE = 64
HIRES_TILE_SIZE = 128

# Shared palette with map export (subset + common terrain).
BLOCK_COLORS: Dict[str, Tuple[int, int, int]] = {
    "minecraft:air": (135, 206, 235),
    "minecraft:cave_air": (135, 206, 235),
    "minecraft:void_air": (135, 206, 235),
    "minecraft:stone": (128, 128, 128),
    "minecraft:granite": (149, 103, 86),
    "minecraft:diorite": (188, 188, 188),
    "minecraft:andesite": (136, 136, 136),
    "minecraft:deepslate": (80, 80, 80),
    "minecraft:grass_block": (34, 139, 34),
    "minecraft:dirt": (139, 69, 19),
    "minecraft:coarse_dirt": (119, 85, 59),
    "minecraft:podzol": (92, 63, 28),
    "minecraft:mud": (60, 57, 61),
    "minecraft:sand": (238, 214, 175),
    "minecraft:red_sand": (190, 102, 33),
    "minecraft:gravel": (136, 136, 136),
    "minecraft:clay": (159, 164, 177),
    "minecraft:water": (64, 164, 223),
    "minecraft:lava": (207, 16, 32),
    "minecraft:snow": (255, 255, 255),
    "minecraft:snow_block": (240, 251, 251),
    "minecraft:ice": (151, 210, 255),
    "minecraft:packed_ice": (141, 180, 250),
    "minecraft:blue_ice": (116, 167, 253),
    "minecraft:bedrock": (85, 85, 85),
    "minecraft:oak_log": (139, 90, 43),
    "minecraft:birch_log": (216, 215, 210),
    "minecraft:spruce_log": (58, 37, 16),
    "minecraft:dark_oak_log": (60, 46, 26),
    "minecraft:jungle_log": (85, 68, 25),
    "minecraft:acacia_log": (103, 96, 86),
    "minecraft:oak_leaves": (0, 100, 0),
    "minecraft:birch_leaves": (90, 126, 58),
    "minecraft:spruce_leaves": (45, 84, 45),
    "minecraft:dark_oak_leaves": (30, 70, 20),
    "minecraft:jungle_leaves": (30, 100, 20),
    "minecraft:azalea_leaves": (90, 140, 50),
    "minecraft:cobblestone": (169, 169, 169),
    "minecraft:mossy_cobblestone": (110, 130, 100),
    "minecraft:sandstone": (218, 210, 158),
    "minecraft:red_sandstone": (181, 97, 31),
    "minecraft:coal_ore": (67, 67, 67),
    "minecraft:iron_ore": (216, 175, 147),
    "minecraft:gold_ore": (255, 215, 0),
    "minecraft:diamond_ore": (0, 191, 255),
    "minecraft:emerald_ore": (0, 201, 87),
    "minecraft:copper_ore": (125, 127, 95),
    "minecraft:obsidian": (20, 18, 29),
    "minecraft:netherrack": (139, 0, 0),
    "minecraft:soul_sand": (84, 64, 51),
    "minecraft:soul_soil": (76, 58, 47),
    "minecraft:glowstone": (255, 198, 73),
    "minecraft:end_stone": (221, 223, 165),
    "minecraft:basalt": (73, 72, 78),
    "minecraft:blackstone": (42, 36, 41),
    "minecraft:crimson_nylium": (130, 31, 31),
    "minecraft:warped_nylium": (22, 124, 132),
    "minecraft:mycelium": (111, 99, 105),
    "minecraft:terracotta": (152, 94, 68),
    "minecraft:white_terracotta": (210, 178, 161),
    "minecraft:orange_terracotta": (162, 84, 38),
    "minecraft:yellow_terracotta": (186, 133, 35),
    "minecraft:brown_terracotta": (77, 51, 36),
    "minecraft:red_terracotta": (143, 61, 47),
    "minecraft:light_gray_terracotta": (135, 107, 98),
    "minecraft:farmland": (95, 58, 31),
    "minecraft:moss_block": (89, 109, 45),
    "minecraft:sculk": (13, 43, 48),
    "minecraft:calcite": (223, 224, 221),
    "minecraft:tuff": (108, 109, 103),
    "minecraft:dripstone_block": (134, 107, 92),
    "minecraft:amethyst_block": (133, 97, 191),
}


def _color_for_block_name(name: str) -> Tuple[int, int, int]:
    try:
        if name in BLOCK_COLORS:
            return BLOCK_COLORS[name]
        if "leaves" in name:
            return (0, 100, 0)
        if "log" in name or "wood" in name:
            return (120, 85, 45)
        if "water" in name:
            return (64, 164, 223)
        if "lava" in name:
            return (207, 16, 32)
        if "ore" in name:
            return (100, 100, 100)
        if "sand" in name:
            return (238, 214, 175)
        if "dirt" in name or "podzol" in name:
            return (139, 69, 19)
        if "grass" in name:
            return (34, 139, 34)
        if "stone" in name or "deepslate" in name:
            return (128, 128, 128)
        if "nether" in name or "netherrack" in name:
            return (139, 0, 0)
        if "snow" in name or "ice" in name:
            return (220, 240, 255)
        h = hashlib.md5(name.encode("utf-8")).digest()
        return (h[0], h[1], h[2])
    except Exception:
        return (128, 128, 128)


def _color_for_block(block: Any) -> Tuple[int, int, int]:
    """Back-compat for callers that still pass anvil Block-like objects."""
    try:
        name = block.name() if hasattr(block, "name") else str(getattr(block, "id", block))
        return _color_for_block_name(str(name))
    except Exception:
        return (128, 128, 128)


def render_region_topview(
    region_file: Path | str,
    tile_size: int = DEFAULT_TILE_SIZE,
    *,
    use_disk_cache: bool = True,
) -> Optional[bytes]:
    """Render one MCA region to PNG bytes (RGB) via core.mca."""
    if not PIL_AVAILABLE:
        return None

    region_path = Path(region_file)
    if not region_path.is_file():
        return None

    tile_size = max(8, min(256, int(tile_size)))

    if use_disk_cache:
        try:
            from core.mca.tile_cache import load_tile

            cached = load_tile(region_path, tile_size)
            if cached:
                return cached
        except Exception:
            pass

    try:
        from core.mca.surface import sample_region_surface_colors

        grid = sample_region_surface_colors(
            region_path,
            tile_size=tile_size,
            color_for_block=_color_for_block_name,
        )
    except Exception:
        return None

    if grid is None:
        return None

    image = Image.new("RGB", (tile_size, tile_size), color=(40, 55, 45))
    try:
        image.putdata([c for row in grid for c in row])
    except Exception:
        pixels = image.load()
        for pz, row in enumerate(grid):
            for px, color in enumerate(row):
                pixels[px, pz] = color

    buf = io.BytesIO()
    try:
        image.save(buf, format="PNG", optimize=False, compress_level=1)
        png = buf.getvalue()
    except Exception:
        return None
    finally:
        image.close()

    if use_disk_cache and png:
        try:
            from core.mca.tile_cache import store_tile

            store_tile(region_path, tile_size, png)
        except Exception:
            pass
    return png


def render_region_topview_base64(
    region_file: Path | str,
    tile_size: int = DEFAULT_TILE_SIZE,
) -> Optional[str]:
    """Same as render_region_topview but returns a base64 string for Image.src."""
    import base64

    raw = render_region_topview(region_file, tile_size=tile_size)
    if raw is None:
        return None
    return base64.b64encode(raw).decode("ascii")
