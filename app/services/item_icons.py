"""内置物品图标 - 使用 Emoji 作为纹理替代方案"""

# 常用物品的 Emoji 映射
ITEM_EMOJI_MAP = {
    # 矿物和材料
    "minecraft:diamond": "💎",
    "minecraft:iron_ingot": "🔩",
    "minecraft:gold_ingot": "🟡",
    "minecraft:emerald": "💚",
    "minecraft:coal": "⚫",
    "minecraft:redstone": "🔴",
    "minecraft:lapis_lazuli": "🔵",
    "minecraft:copper_ingot": "🟠",
    "minecraft:netherite_ingot": "⬛",
    "minecraft:amethyst_shard": "🟣",

    # 工具
    "minecraft:diamond_sword": "⚔️",
    "minecraft:diamond_pickaxe": "⛏️",
    "minecraft:diamond_axe": "🪓",
    "minecraft:diamond_shovel": "🥄",
    "minecraft:iron_sword": "🗡️",
    "minecraft:iron_pickaxe": "⛏️",
    "minecraft:bow": "🏹",
    "minecraft:crossbow": "🏹",
    "minecraft:trident": "🔱",
    "minecraft:fishing_rod": "🎣",
    "minecraft:shears": "✂️",

    # 盔甲
    "minecraft:diamond_helmet": "🪖",
    "minecraft:diamond_chestplate": "👔",
    "minecraft:diamond_leggings": "👖",
    "minecraft:diamond_boots": "👢",
    "minecraft:elytra": "🦅",
    "minecraft:shield": "🛡️",

    # 食物
    "minecraft:apple": "🍎",
    "minecraft:bread": "🍞",
    "minecraft:cooked_beef": "🥩",
    "minecraft:cooked_porkchop": "🥓",
    "minecraft:cooked_chicken": "🍗",
    "minecraft:golden_apple": "🍏",
    "minecraft:enchanted_golden_apple": "✨",
    "minecraft:golden_carrot": "🥕",
    "minecraft:cake": "🍰",
    "minecraft:cookie": "🍪",
    "minecraft:melon_slice": "🍉",
    "minecraft:honey_bottle": "🍯",

    # 方块
    "minecraft:dirt": "🟤",
    "minecraft:grass_block": "🟩",
    "minecraft:stone": "🪨",
    "minecraft:cobblestone": "⬜",
    "minecraft:sand": "🟨",
    "minecraft:glass": "🔲",
    "minecraft:oak_log": "🪵",
    "minecraft:oak_planks": "🟫",
    "minecraft:chest": "📦",
    "minecraft:ender_chest": "🎁",
    "minecraft:crafting_table": "🔨",
    "minecraft:furnace": "🔥",
    "minecraft:beacon": "🔆",
    "minecraft:torch": "🔦",
    "minecraft:tnt": "💣",
    "minecraft:obsidian": "⬛",
    "minecraft:bedrock": "▓",

    # 特殊物品
    "minecraft:totem_of_undying": "🗿",
    "minecraft:nether_star": "⭐",
    "minecraft:ender_pearl": "🔮",
    "minecraft:ender_eye": "👁️",
    "minecraft:blaze_rod": "🔥",
    "minecraft:ghast_tear": "💧",
    "minecraft:book": "📖",
    "minecraft:enchanted_book": "📘",
    "minecraft:map": "🗺️",
    "minecraft:compass": "🧭",
    "minecraft:clock": "⏰",
    "minecraft:bucket": "🪣",
    "minecraft:water_bucket": "💧",
    "minecraft:lava_bucket": "🌋",
    "minecraft:saddle": "🏇",
    "minecraft:name_tag": "🏷️",
    "minecraft:lead": "🪢",

    # 药水相关
    "minecraft:potion": "🧪",
    "minecraft:splash_potion": "💊",
    "minecraft:experience_bottle": "✨",
    "minecraft:brewing_stand": "⚗️",

    # 唱片
    "minecraft:music_disc_13": "💿",
    "minecraft:music_disc_cat": "💿",
    "minecraft:jukebox": "📻",
}


def get_item_emoji(item_id: str) -> str:
    """获取物品对应的 Emoji，如果没有则返回默认图标"""
    if item_id in ITEM_EMOJI_MAP:
        return ITEM_EMOJI_MAP[item_id]

    # 基于物品类型的智能回退
    if not item_id or ":" not in item_id:
        return "📦"

    _, local_id = item_id.split(":", 1)

    # 工具类
    if "sword" in local_id:
        return "⚔️"
    if "pickaxe" in local_id:
        return "⛏️"
    if "axe" in local_id:
        return "🪓"
    if "shovel" in local_id or "spade" in local_id:
        return "🥄"
    if "hoe" in local_id:
        return "🚜"

    # 盔甲类
    if "helmet" in local_id:
        return "🪖"
    if "chestplate" in local_id:
        return "👔"
    if "leggings" in local_id:
        return "👖"
    if "boots" in local_id:
        return "👢"

    # 方块类
    if "_ore" in local_id:
        return "⛰️"
    if "_log" in local_id or "wood" in local_id:
        return "🪵"
    if "_planks" in local_id:
        return "🟫"
    if "stone" in local_id:
        return "🪨"
    if "dirt" in local_id or "grass" in local_id:
        return "🟫"
    if "glass" in local_id:
        return "🔲"

    # 食物类
    if "food" in local_id or "cooked" in local_id or "bread" in local_id or "stew" in local_id:
        return "🍖"

    # 默认
    return "📦"
