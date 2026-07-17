"""Common constants for entity/block/container search."""

from typing import Dict, List, Tuple

COMMON_ENTITIES = [
    "minecraft:villager", "minecraft:creeper", "minecraft:zombie", "minecraft:skeleton",
    "minecraft:spider", "minecraft:enderman", "minecraft:cow", "minecraft:pig",
    "minecraft:sheep", "minecraft:chicken", "minecraft:wolf", "minecraft:cat",
    "minecraft:horse", "minecraft:minecart", "minecraft:item_frame", "minecraft:armor_stand",
]

COMMON_BLOCKS = [
    "minecraft:diamond_ore", "minecraft:deepslate_diamond_ore", "minecraft:ancient_debris",
    "minecraft:emerald_ore", "minecraft:gold_ore", "minecraft:iron_ore", "minecraft:coal_ore",
    "minecraft:redstone_ore", "minecraft:lapis_ore", "minecraft:spawner", "minecraft:chest",
    "minecraft:trapped_chest", "minecraft:barrel", "minecraft:shulker_box", "minecraft:ender_chest",
    "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker", "minecraft:hopper",
    "minecraft:dropper", "minecraft:dispenser", "minecraft:beacon", "minecraft:dragon_egg",
]

COMMON_CONTAINERS = [
    "minecraft:chest", "minecraft:trapped_chest", "minecraft:barrel", "minecraft:shulker_box",
    "minecraft:white_shulker_box", "minecraft:orange_shulker_box", "minecraft:magenta_shulker_box",
    "minecraft:light_blue_shulker_box", "minecraft:yellow_shulker_box",
    "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box", "minecraft:gray_shulker_box", "minecraft:light_gray_shulker_box",
    "minecraft:cyan_shulker_box", "minecraft:purple_shulker_box", "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box", "minecraft:green_shulker_box", "minecraft:red_shulker_box",
    "minecraft:black_shulker_box", "minecraft:furnace", "minecraft:blast_furnace",
    "minecraft:smoker",
    "minecraft:hopper", "minecraft:dropper", "minecraft:dispenser", "minecraft:brewing_stand",
]

MAX_RESULTS = 10000
VALID_SEARCH_TYPES = {"entity", "block", "container"}
VALID_DIMENSIONS = {"overworld", "nether", "end"}

# UI 预设列表（带中文标签）
ENTITY_PRESETS: List[Tuple[str, str]] = [
    ("minecraft:villager", "村民"),
    ("minecraft:zombie", "僵尸"),
    ("minecraft:skeleton", "骷髅"),
    ("minecraft:creeper", "苦力怕"),
    ("minecraft:spider", "蜘蛛"),
    ("minecraft:enderman", "末影人"),
    ("minecraft:pig", "猪"),
    ("minecraft:cow", "牛"),
    ("minecraft:sheep", "羊"),
    ("minecraft:chicken", "鸡"),
]

BLOCK_PRESETS: List[Tuple[str, str]] = [
    ("minecraft:diamond_ore", "钻石矿石"),
    ("minecraft:iron_ore", "铁矿石"),
    ("minecraft:gold_ore", "金矿石"),
    ("minecraft:coal_ore", "煤矿石"),
    ("minecraft:emerald_ore", "绿宝石矿石"),
    ("minecraft:ancient_debris", "远古残骸"),
]

CONTAINER_PRESETS: List[Tuple[str, str]] = [
    ("minecraft:chest", "箱子"),
    ("minecraft:barrel", "木桶"),
    ("minecraft:shulker_box", "潜影盒"),
    ("minecraft:hopper", "漏斗"),
    ("minecraft:furnace", "熔炉"),
]

PRESETS: Dict[str, List[Tuple[str, str]]] = {
    "entity": ENTITY_PRESETS,
    "block": BLOCK_PRESETS,
    "container": CONTAINER_PRESETS,
}


def get_preset_options(search_type: str) -> List[Tuple[str, str]]:
    """返回指定搜索类型的预设列表。"""
    return PRESETS.get(search_type, [])
