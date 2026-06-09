"""Common constants for entity/block/container search."""

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
    "minecraft:light_blue_shulker_box", "minecraft:yellow_shulker_box", "minecraft:lime_shulker_box",
    "minecraft:pink_shulker_box", "minecraft:gray_shulker_box", "minecraft:light_gray_shulker_box",
    "minecraft:cyan_shulker_box", "minecraft:purple_shulker_box", "minecraft:blue_shulker_box",
    "minecraft:brown_shulker_box", "minecraft:green_shulker_box", "minecraft:red_shulker_box",
    "minecraft:black_shulker_box", "minecraft:furnace", "minecraft:blast_furnace", "minecraft:smoker",
    "minecraft:hopper", "minecraft:dropper", "minecraft:dispenser", "minecraft:brewing_stand",
]

MAX_RESULTS = 10000
VALID_SEARCH_TYPES = {"entity", "block", "container"}
VALID_DIMENSIONS = {"overworld", "nether", "end"}
