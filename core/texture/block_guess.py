"""Pure helpers for guessing whether a Minecraft id is a block texture."""
from __future__ import annotations

_BLOCK_SUFFIXES = (
    "_block", "_ore", "_log", "_wood", "_stem", "_planks", "_stone",
    "_bricks", "_glass", "_wool", "_carpet", "_bed", "_door", "_fence",
    "_wall", "_slab", "_stairs", "_pane", "_shulker_box", "_leaves",
    "_sand", "_concrete", "_terracotta", "_glazed_terracotta",
    "_copper", "_nylium", "_basalt", "_blackstone", "_deepslate",
    "_concrete_powder",
)
_BLOCK_PREFIXES = (
    "chest", "barrel", "composter", "lectern", "beehive", "campfire",
    "torch", "lantern", "anvil", "cauldron", "brewing_stand",
    "enchanting_table", "end_rod", "observer", "piston", "hopper",
    "dispenser", "dropper", "furnace", "tnt", "note_block",
    "jukebox", "respawn_anchor", "lodestone",
)
_BLOCK_EXACT = {
    "dirt", "grass_block", "stone", "cobblestone", "glass", "sand",
    "gravel", "obsidian", "crying_obsidian", "bedrock", "crafting_table",
    "chest", "ender_chest", "beacon", "moss_block", "mud", "clay",
    "snow_block", "ice", "packed_ice", "blue_ice", "sponge", "wet_sponge",
    "melon", "pumpkin", "hay_block", "bone_block", "dried_kelp_block",
    "slime_block", "honey_block", "mushroom_stem",
    "smooth_stone", "sandstone", "red_sandstone", "prismarine",
    "netherrack", "nether_bricks", "red_nether_bricks", "end_stone",
    "purpur_block", "quartz_block", "amethyst_block", "calcite",
    "tuff", "dripstone_block", "pointed_dripstone",
    "sculk", "sculk_catalyst", "sculk_shrieker", "sculk_sensor",
    "mangrove_roots", "muddy_mangrove_roots",
    "ochre_froglight", "verdant_froglight", "pearlescent_froglight",
    "reinforced_deepslate", "frogspawn",
    "sea_lantern", "glowstone", "redstone_lamp",
    "coal_block", "iron_block", "gold_block", "diamond_block",
    "emerald_block", "lapis_block", "redstone_block", "netherite_block",
    "copper_block", "raw_iron_block", "raw_gold_block", "raw_copper_block",
    "white_wool", "orange_wool", "magenta_wool", "light_blue_wool",
    "yellow_wool", "lime_wool", "pink_wool", "gray_wool",
    "light_gray_wool", "cyan_wool", "purple_wool", "blue_wool",
    "brown_wool", "green_wool", "red_wool", "black_wool",
}


def guess_is_block(local_id: str) -> bool:
    """Return True when a bare Minecraft id looks like a block texture."""
    if local_id in _BLOCK_EXACT:
        return True
    for prefix in _BLOCK_PREFIXES:
        if local_id.startswith(prefix):
            return True
    for suffix in _BLOCK_SUFFIXES:
        if local_id.endswith(suffix):
            return True
    return False


def resolve_texture_resource_key(
    local_id: str,
    *,
    prefer_block: bool,
    asset_keys: dict[str, str] | None,
) -> str:
    """Choose block/item texture path for a local id against an asset index."""
    block_key = f"textures/block/{local_id}.png"
    item_key = f"textures/item/{local_id}.png"

    def has(res_path: str) -> bool:
        if asset_keys is None:
            return False
        return f"minecraft/{res_path}" in asset_keys

    if prefer_block:
        if has(block_key):
            return block_key
        if has(item_key):
            return item_key
        return block_key

    if has(item_key):
        return item_key
    if has(block_key):
        return block_key
    return item_key
