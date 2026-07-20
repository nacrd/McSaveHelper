"""Top-down (bird's-eye) region tile renderer for the map display.

Renders one r.x.z.mca region into a small PNG suitable for Canvas tiles.
Uses native core.mca (heightmap + palette) instead of anvil-parser.
"""
from __future__ import annotations

import hashlib
import io
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from core.mca.texture_palette import average_block_texture

try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:  # pragma: no cover
    PIL_AVAILABLE = False

# Progressive tile ladder (pixels per region edge).
# 16 -> fast first paint; 32 overview; 64 region focus; 128 chunk inspection;
# 256 -> deep inspection; 512 -> one pixel per Minecraft block at high zoom.
PREVIEW_TILE_SIZE = 16
DEFAULT_TILE_SIZE = 32
DETAIL_TILE_SIZE = 64
HIRES_TILE_SIZE = 128
ULTRA_TILE_SIZE = 256
LEAF_TILE_SIZE = 512

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
Color = Tuple[int, int, int]
ColorGrid = List[List[Color]]

_MATERIAL_RULES: Tuple[Tuple[Tuple[str, ...], Color], ...] = (
    (("leaves",), (0, 100, 0)),
    (("log", "wood", "planks"), (120, 85, 45)),
    (("water",), (64, 164, 223)),
    (("lava",), (207, 16, 32)),
    (("ore",), (118, 116, 105)),
    (("sand",), (238, 214, 175)),
    (("dirt", "podzol"), (139, 69, 19)),
    (("grass", "moss"), (34, 139, 34)),
    (("stone", "deepslate"), (128, 128, 128)),
    (("nether", "netherrack"), (139, 0, 0)),
    (("snow", "ice"), (220, 240, 255)),
    (("brick",), (150, 72, 55)),
    (("terracotta",), (177, 92, 65)),
    (("concrete",), (150, 150, 150)),
    (("quartz", "calcite"), (225, 222, 210)),
    (("prismarine",), (75, 155, 145)),
    (("copper",), (184, 108, 78)),
    (("coral",), (224, 105, 130)),
)

# Wood is represented by several blocks in a world, but those blocks share
# one map material.  Keep the structural suffixes explicit so an unrelated
# block such as ``stone_pressure_plate`` cannot be mistaken for wood.
_WOOD_FAMILY_TOKENS = frozenset(
    {
        "acacia",
        "bamboo",
        "birch",
        "cherry",
        "crimson",
        "jungle",
        "mangrove",
        "oak",
        "spruce",
        "warped",
    }
)
_WOOD_COMPONENT_TOKENS = frozenset(
    {
        "button",
        "door",
        "fence",
        "gate",
        "hyphae",
        "log",
        "planks",
        "plate",
        "roots",
        "sign",
        "slab",
        "stairs",
        "stem",
        "trapdoor",
        "wall",
        "wood",
    }
)
_WOOD_COLOR: Color = (120, 85, 45)
_DIRT_PATH_COLOR: Color = BLOCK_COLORS["minecraft:dirt"]
_MATERIAL_COMPONENT_SUFFIXES = frozenset(
    {
        "button",
        "door",
        "fence",
        "gate",
        "hanging",
        "log",
        "plate",
        "planks",
        "pressure",
        "sign",
        "slab",
        "stairs",
        "trapdoor",
        "wall",
        "wood",
    }
)
_MATERIAL_VARIANT_COLORS: Dict[str, Color] = {
    block_name.split(":", 1)[-1]: color
    for block_name, color in BLOCK_COLORS.items()
}

_NATURAL_SURFACE_COLORS: Dict[str, Color] = {
    "vine": (65, 112, 52),
    "short_grass": (79, 139, 58),
    "tall_grass": (72, 132, 54),
    "fern": (68, 119, 54),
    "large_fern": (61, 111, 49),
    "leaf_litter": (113, 101, 62),
    "lily_pad": (57, 108, 56),
    "seagrass": (48, 119, 91),
    "tall_seagrass": (44, 111, 84),
    "kelp": (51, 105, 64),
    "kelp_plant": (48, 99, 61),
    "sugar_cane": (106, 153, 75),
    "sweet_berry_bush": (76, 116, 58),
    "firefly_bush": (72, 118, 61),
    "bush": (78, 123, 62),
    "dead_bush": (116, 103, 69),
    "moss_carpet": (82, 111, 48),
    "wheat": (145, 142, 67),
    "carrots": (83, 132, 58),
    "potatoes": (91, 130, 62),
    "beetroots": (82, 119, 62),
}
_FLOWER_COLOR: Color = (139, 125, 91)
_FLOWER_BLOCKS = frozenset(
    {
        "allium",
        "azure_bluet",
        "blue_orchid",
        "closed_eyeblossom",
        "cornflower",
        "dandelion",
        "flowering_azalea",
        "lilac",
        "lily_of_the_valley",
        "open_eyeblossom",
        "orange_tulip",
        "oxeye_daisy",
        "peony",
        "pink_petals",
        "pink_tulip",
        "poppy",
        "red_tulip",
        "rose_bush",
        "sunflower",
        "torchflower",
        "white_tulip",
        "wither_rose",
    }
)

# Vanilla temperature maps are unavailable when only an MCA is open.  These
# subdued category colors approximate their role without inventing saturated
# colors for unknown or modded biomes.
_DEFAULT_BIOME_TINTS: Dict[str, Color] = {
    "grass": (127, 178, 80),
    "foliage": (113, 167, 78),
    "water": (63, 118, 228),
}
_BIOME_TINT_RULES: Tuple[
    Tuple[Tuple[str, ...], Dict[str, Color]],
    ...,
] = (
    (
        ("swamp", "mangrove"),
        {
            "grass": (106, 134, 61),
            "foliage": (82, 121, 61),
            "water": (91, 134, 116),
        },
    ),
    (
        ("jungle", "bamboo"),
        {
            "grass": (78, 171, 58),
            "foliage": (62, 157, 53),
            "water": (52, 129, 211),
        },
    ),
    (
        ("dark_forest",),
        {
            "grass": (80, 130, 61),
            "foliage": (64, 115, 54),
            "water": (58, 113, 191),
        },
    ),
    (
        ("forest", "grove"),
        {
            "grass": (95, 157, 70),
            "foliage": (75, 139, 62),
            "water": (60, 119, 210),
        },
    ),
    (
        ("taiga", "old_growth"),
        {
            "grass": (126, 154, 85),
            "foliage": (102, 137, 77),
            "water": (58, 111, 181),
        },
    ),
    (
        ("snow", "frozen", "ice_spikes"),
        {
            "grass": (128, 154, 137),
            "foliage": (110, 143, 123),
            "water": (62, 87, 146),
        },
    ),
    (
        ("desert", "badlands", "savanna"),
        {
            "grass": (169, 164, 84),
            "foliage": (143, 148, 77),
            "water": (55, 128, 204),
        },
    ),
    (
        ("lukewarm_ocean",),
        {"water": (46, 129, 218)},
    ),
    (
        ("warm_ocean",),
        {"water": (38, 139, 218)},
    ),
    (
        ("cold_ocean",),
        {"water": (55, 105, 175)},
    ),
)


def _block_path(name: str) -> str:
    """Return a lowercase block path without its optional namespace."""
    normalized = name.strip().lower()
    return normalized.rsplit(":", 1)[-1]


def _biome_material_kind(block_path: str) -> Optional[str]:
    """Return the tint family used by vanilla biome color resolvers."""
    tokens = frozenset(block_path.split("_"))
    if (
        "water" in tokens
        or block_path == "bubble_column"
        or block_path in {"ice", "packed_ice", "blue_ice", "frosted_ice"}
    ):
        return "water"
    if (
        "leaves" in tokens
        or "leaf" in tokens
        or block_path in {
            "vine",
            "lily_pad",
            "seagrass",
            "tall_seagrass",
            "kelp",
            "kelp_plant",
            "sugar_cane",
            "sweet_berry_bush",
            "firefly_bush",
            "bush",
        }
    ):
        return "foliage"
    if (
        block_path in {
            "grass_block",
            "grass",
            "short_grass",
            "tall_grass",
            "fern",
            "large_fern",
            "moss_block",
            "moss_carpet",
            "wheat",
            "carrots",
            "potatoes",
            "beetroots",
        }
        or block_path.endswith("_grass")
    ):
        return "grass"
    return None


def _natural_surface_color(block_path: str) -> Optional[Color]:
    exact = _NATURAL_SURFACE_COLORS.get(block_path)
    if exact is not None:
        return exact
    if (
        block_path in _FLOWER_BLOCKS
        or block_path.endswith("_flower")
        or block_path.endswith("_flowers")
    ):
        return _FLOWER_COLOR
    if block_path.endswith("_bush"):
        return (82, 116, 66)
    if block_path.endswith("_vine") or block_path.endswith("_vines"):
        return _NATURAL_SURFACE_COLORS["vine"]
    return None


def _is_gray_texture(color: Color) -> bool:
    """Detect vanilla tint-mask textures that should not render as grey."""
    return max(color) - min(color) <= 18


def _biome_tint(biome: Optional[str], kind: str) -> Optional[Color]:
    if not biome:
        return None
    path = biome.strip().lower().rsplit(":", 1)[-1]
    if not path or any(token in path for token in ("nether", "end", "void")):
        return None
    for biome_tokens, colors in _BIOME_TINT_RULES:
        if any(token in path for token in biome_tokens):
            return colors.get(kind, _DEFAULT_BIOME_TINTS.get(kind))
    return _DEFAULT_BIOME_TINTS.get(kind)


def _blend_biome_tint(base: Color, tint: Color, amount: float) -> Color:
    amount = max(0.0, min(1.0, amount))
    return (
        int(round(base[0] * (1.0 - amount) + tint[0] * amount)),
        int(round(base[1] * (1.0 - amount) + tint[1] * amount)),
        int(round(base[2] * (1.0 - amount) + tint[2] * amount)),
    )


def _variant_material_color(block_path: str) -> Optional[Color]:
    """Resolve structural variants to the material shown by the map."""
    tokens = frozenset(block_path.split("_"))

    # A path is ground, not grass.  Check this before the generic grass rule.
    if "path" in tokens and tokens.intersection({"dirt", "grass"}):
        return _DIRT_PATH_COLOR

    if "leaves" in tokens or "leaf" in tokens:
        return BLOCK_COLORS["minecraft:oak_leaves"]

    material_tokens = list(block_path.split("_"))
    while material_tokens and material_tokens[-1] in _MATERIAL_COMPONENT_SUFFIXES:
        material_tokens.pop()
    material_stem = "_".join(material_tokens)
    material_color = _MATERIAL_VARIANT_COLORS.get(material_stem)
    if material_color is not None:
        return material_color

    if tokens.intersection(_WOOD_FAMILY_TOKENS) and tokens.intersection(
        _WOOD_COMPONENT_TOKENS
    ):
        return _WOOD_COLOR

    return None


def _color_for_block_name(name: str) -> Tuple[int, int, int]:
    """Map a block id to a stable, Minecraft-style top-view material color."""
    normalized = name.strip().lower()
    block_path = _block_path(normalized)
    texture_color = average_block_texture(normalized)
    tint_kind = _biome_material_kind(block_path)
    if texture_color is not None and not (
        tint_kind is not None and _is_gray_texture(texture_color)
    ):
        return texture_color

    exact = BLOCK_COLORS.get(normalized)
    if exact is not None:
        return exact

    exact = BLOCK_COLORS.get(f"minecraft:{block_path}")
    if exact is not None:
        return exact

    natural = _natural_surface_color(block_path)
    if natural is not None:
        return natural

    variant = _variant_material_color(block_path)
    if variant is not None:
        return variant

    tokens = frozenset(block_path.split("_"))
    for material_tokens, color in _MATERIAL_RULES:
        if tokens.intersection(material_tokens):
            return color

    # Unknown modded blocks should remain distinguishable without the
    # saturated MD5 rainbow that made terrain look like random noise.
    h = hashlib.md5(normalized.encode("utf-8")).digest()
    return (
        48 + int(h[0] * 0.55),
        48 + int(h[1] * 0.55),
        48 + int(h[2] * 0.55),
    )


def _color_for_surface_sample(name: str, biome: Optional[str]) -> Color:
    """Resolve a material color and apply a restrained biome tint."""
    base = _color_for_block_name(name)
    kind = _biome_material_kind(_block_path(name))
    if kind is None:
        return base
    tint = _biome_tint(biome, kind)
    if tint is None:
        return base
    amount = {"grass": 0.42, "foliage": 0.38, "water": 0.34}[kind]
    return _blend_biome_tint(base, tint, amount)


def _load_cached_tile(region_path: Path, tile_size: int) -> Optional[bytes]:
    try:
        from core.mca.tile_cache import load_tile

        return load_tile(region_path, tile_size)
    except Exception:
        return None


@lru_cache(maxsize=4096)
def _uses_external_streams_cached(
    path: str,
    _mtime_ns: int,
    _size: int,
) -> bool:
    try:
        from core.mca.region_file import RegionFile

        with RegionFile.open(path) as region:
            return region.has_external_chunks()
    except Exception:
        return False


def _uses_external_streams(region_path: Path) -> bool:
    """External MCC payloads bypass the disk PNG cache for freshness."""
    try:
        stat = region_path.stat()
        return _uses_external_streams_cached(
            str(region_path.resolve()),
            stat.st_mtime_ns,
            stat.st_size,
        )
    except OSError:
        return False


def _sample_surface_grid(
    region_path: Path,
    tile_size: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    status_out: Optional[List[bool]] = None,
) -> Optional[ColorGrid]:
    try:
        from core.mca.surface import sample_region_surface_colors

        failed_chunks: set[Tuple[int, int]] = set()

        # A tile usually reuses a small set of block/biome pairs.  Keep this
        # cache local to the render so changing the texture JAR cannot leave
        # stale colors in a process-wide cache.
        @lru_cache(maxsize=4096)
        def cached_surface_color(
            name: str,
            biome: Optional[str],
        ) -> Color:
            return _color_for_surface_sample(name, biome)

        grid = sample_region_surface_colors(
            region_path,
            tile_size=tile_size,
            color_for_block=_color_for_block_name,
            color_for_surface=cached_surface_color,
            cancel_check=cancel_check,
            decode_workers=decode_workers,
            failed_chunks=failed_chunks,
        )
        if status_out is not None:
            status_out.append(grid is not None and not failed_chunks)
        return grid
    except Exception:
        if status_out is not None:
            status_out.append(False)
        return None


def _encode_png(grid: ColorGrid, tile_size: int) -> Optional[bytes]:
    image = Image.new("RGB", (tile_size, tile_size), color=(40, 55, 45))
    try:
        try:
            image.putdata([color for row in grid for color in row])
        except Exception:
            pixels = image.load()
            if pixels is None:
                return None
            for pz, row in enumerate(grid):
                for px, color in enumerate(row):
                    pixels[px, pz] = color

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=False, compress_level=1)
        return buffer.getvalue()
    except Exception:
        return None
    finally:
        image.close()


def _store_cached_tile(
    region_path: Path,
    tile_size: int,
    png: bytes,
) -> None:
    try:
        from core.mca.tile_cache import store_tile

        store_tile(region_path, tile_size, png)
    except Exception:
        pass


def _load_cached_topview(
    region_path: Path,
    tile_size: int,
    cache_allowed: bool,
    cancel_check: Optional[Callable[[], bool]],
    status_out: List[bool],
) -> Optional[bytes]:
    if not cache_allowed:
        return None
    cached = _load_cached_tile(region_path, tile_size)
    if not cached or (cancel_check is not None and cancel_check()):
        return None
    status_out.append(True)
    return cached


def _render_topview_png(
    region_path: Path,
    tile_size: int,
    cache_allowed: bool,
    cancel_check: Optional[Callable[[], bool]],
    decode_workers: Optional[int],
    status_out: List[bool],
) -> Optional[bytes]:
    grid = _sample_surface_grid(
        region_path,
        tile_size,
        cancel_check=cancel_check,
        decode_workers=decode_workers,
        status_out=status_out,
    )
    if grid is None or (cancel_check is not None and cancel_check()):
        return None
    png = _encode_png(grid, tile_size)
    if png is None or (cancel_check is not None and cancel_check()):
        return None
    if cache_allowed and status_out and status_out[-1]:
        _store_cached_tile(region_path, tile_size, png)
    return png


def render_region_topview(
    region_file: Path | str,
    tile_size: int = DEFAULT_TILE_SIZE,
    *,
    use_disk_cache: bool = True,
    cancel_check: Optional[Callable[[], bool]] = None,
    decode_workers: Optional[int] = None,
    status_out: Optional[List[bool]] = None,
) -> Optional[bytes]:
    """Render one MCA region to PNG bytes (RGB) via core.mca."""
    if not PIL_AVAILABLE:
        return None

    region_path = Path(region_file)
    if not region_path.is_file():
        return None

    if cancel_check is not None and cancel_check():
        return None

    tile_size = max(8, min(LEAF_TILE_SIZE, int(tile_size)))
    render_status = status_out if status_out is not None else []

    cache_allowed = use_disk_cache and not _uses_external_streams(region_path)
    cached = _load_cached_topview(
        region_path,
        tile_size,
        cache_allowed,
        cancel_check,
        render_status,
    )
    if cached is not None:
        return cached
    if cancel_check is not None and cancel_check():
        return None
    return _render_topview_png(
        region_path,
        tile_size,
        cache_allowed,
        cancel_check,
        decode_workers,
        render_status,
    )


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
