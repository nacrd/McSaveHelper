"""Item service constants: vanilla names, enchantments, durability."""
from typing import Dict, Optional


_VANILLA_ITEM_NAMES: Dict[str, str] = {
    "minecraft:diamond": "钻石", "minecraft:iron_ingot": "铁锭", "minecraft:gold_ingot": "金锭",
    "minecraft:coal": "煤炭", "minecraft:emerald": "绿宝石", "minecraft:lapis_lazuli": "青金石",
    "minecraft:redstone": "红石", "minecraft:netherite_ingot": "下界合金锭",
    "minecraft:copper_ingot": "铜锭", "minecraft:amethyst_shard": "紫水晶碎片",
    "minecraft:quartz": "下界石英", "minecraft:glowstone_dust": "荧石粉",
    "minecraft:gunpowder": "火药", "minecraft:string": "线", "minecraft:feather": "羽毛",
    "minecraft:flint": "燧石", "minecraft:clay_ball": "粘土球", "minecraft:brick": "红砖",
    "minecraft:prismarine_shard": "海晶碎片", "minecraft:prismarine_crystals": "海晶灯碎片",
    "minecraft:nautilus_shell": "鹦鹉螺壳", "minecraft:heart_of_the_sea": "海洋之心",
    "minecraft:shulker_shell": "潜影壳", "minecraft:phantom_membrane": "幻翼膜",
    "minecraft:blaze_rod": "烈焰棒", "minecraft:blaze_powder": "烈焰粉",
    "minecraft:ender_pearl": "末影珍珠", "minecraft:ender_eye": "末影之眼",
    "minecraft:ghast_tear": "恶魂之泪", "minecraft:magma_cream": "岩浆膏",
    "minecraft:nether_star": "下界之星", "minecraft:totem_of_undying": "不死图腾",
    "minecraft:elytra": "鞘翅", "minecraft:trident": "三叉戟",
    "minecraft:crossbow": "弩", "minecraft:bow": "弓", "minecraft:arrow": "箭",
    "minecraft:diamond_sword": "钻石剑", "minecraft:diamond_pickaxe": "钻石镐",
    "minecraft:diamond_axe": "钻石斧", "minecraft:diamond_shovel": "钻石锹",
    "minecraft:diamond_hoe": "钻石锄", "minecraft:iron_sword": "铁剑",
    "minecraft:iron_pickaxe": "铁镐", "minecraft:iron_axe": "铁斧",
    "minecraft:iron_shovel": "铁锹", "minecraft:iron_hoe": "铁锄",
    "minecraft:golden_sword": "金剑", "minecraft:golden_pickaxe": "金镐",
    "minecraft:golden_axe": "金斧", "minecraft:golden_shovel": "金锹",
    "minecraft:golden_hoe": "金锄", "minecraft:stone_sword": "石剑",
    "minecraft:stone_pickaxe": "石镐", "minecraft:stone_axe": "石斧",
    "minecraft:stone_shovel": "石锹", "minecraft:stone_hoe": "石锄",
    "minecraft:wooden_sword": "木剑", "minecraft:wooden_pickaxe": "木镐",
    "minecraft:wooden_axe": "木斧", "minecraft:wooden_shovel": "木锹",
    "minecraft:wooden_hoe": "木锄", "minecraft:netherite_sword": "下界合金剑",
    "minecraft:netherite_pickaxe": "下界合金镐", "minecraft:netherite_axe": "下界合金斧",
    "minecraft:netherite_shovel": "下界合金锹", "minecraft:netherite_hoe": "下界合金锄",
    "minecraft:shears": "剪刀", "minecraft:flint_and_steel": "打火石",
    "minecraft:fishing_rod": "钓鱼竿", "minecraft:carrot_on_a_stick": "胡萝卜钓竿",
    "minecraft:warped_fungus_on_a_stick": "诡异菌钓竿", "minecraft:brush": "刷子",
    "minecraft:diamond_helmet": "钻石头盔", "minecraft:diamond_chestplate": "钻石胸甲",
    "minecraft:diamond_leggings": "钻石护腿", "minecraft:diamond_boots": "钻石靴子",
    "minecraft:iron_helmet": "铁头盔", "minecraft:iron_chestplate": "铁胸甲",
    "minecraft:iron_leggings": "铁护腿", "minecraft:iron_boots": "铁靴子",
    "minecraft:golden_helmet": "金头盔", "minecraft:golden_chestplate": "金胸甲",
    "minecraft:golden_leggings": "金护腿", "minecraft:golden_boots": "金靴子",
    "minecraft:leather_helmet": "皮革帽子", "minecraft:leather_chestplate": "皮革外套",
    "minecraft:leather_leggings": "皮革裤子", "minecraft:leather_boots": "皮革靴子",
    "minecraft:chainmail_helmet": "锁链头盔", "minecraft:chainmail_chestplate": "锁链胸甲",
    "minecraft:chainmail_leggings": "锁链护腿", "minecraft:chainmail_boots": "锁链靴子",
    "minecraft:netherite_helmet": "下界合金头盔", "minecraft:netherite_chestplate": "下界合金胸甲",
    "minecraft:netherite_leggings": "下界合金护腿", "minecraft:netherite_boots": "下界合金靴子",
    "minecraft:turtle_helmet": "海龟壳",
    "minecraft:apple": "苹果", "minecraft:bread": "面包", "minecraft:cooked_beef": "牛排",
    "minecraft:cooked_porkchop": "熟猪排", "minecraft:cooked_chicken": "熟鸡肉",
    "minecraft:golden_apple": "金苹果", "minecraft:enchanted_golden_apple": "附魔金苹果",
    "minecraft:golden_carrot": "金胡萝卜", "minecraft:baked_potato": "烤马铃薯",
    "minecraft:dirt": "泥土", "minecraft:grass_block": "草方块", "minecraft:stone": "石头",
    "minecraft:cobblestone": "圆石", "minecraft:oak_log": "橡木原木", "minecraft:glass": "玻璃",
    "minecraft:obsidian": "黑曜石", "minecraft:bedrock": "基岩",
    "minecraft:crafting_table": "工作台", "minecraft:furnace": "熔炉",
    "minecraft:chest": "箱子", "minecraft:ender_chest": "末影箱",
    "minecraft:beacon": "信标", "minecraft:anvil": "铁砧",
    "minecraft:enchanting_table": "附魔台", "minecraft:torch": "火把",
    "minecraft:diamond_ore": "钻石矿石", "minecraft:iron_ore": "铁矿石",
    "minecraft:gold_ore": "金矿石", "minecraft:coal_ore": "煤矿石",
    "minecraft:ancient_debris": "远古残骸", "minecraft:enchanted_book": "附魔书",
    "minecraft:potion": "药水", "minecraft:splash_potion": "喷溅药水",
    "minecraft:lingering_potion": "滞留药水",
}

_ENCHANTMENT_NAMES: Dict[str, str] = {
    "minecraft:protection": "保护", "minecraft:fire_protection": "火焰保护",
    "minecraft:feather_falling": "摔落保护", "minecraft:blast_protection": "爆炸保护",
    "minecraft:respiration": "水下呼吸", "minecraft:thorns": "荆棘",
    "minecraft:sharpness": "锋利", "minecraft:smite": "亡灵杀手",
    "minecraft:efficiency": "效率", "minecraft:silk_touch": "精准采集",
    "minecraft:fortune": "时运", "minecraft:power": "力量",
    "minecraft:flame": "火矢", "minecraft:infinity": "无限",
    "minecraft:loyalty": "忠诚", "minecraft:mending": "经验修补",
    "minecraft:unbreaking": "耐久", "minecraft:vanishing_curse": "消失诅咒",
    "minecraft:binding_curse": "绑定诅咒",
}

_MAX_DURABILITY: Dict[str, Optional[int]] = {
    "minecraft:diamond_sword": 1561, "minecraft:diamond_pickaxe": 1561,
    "minecraft:netherite_sword": 2031, "minecraft:netherite_pickaxe": 2031,
    "minecraft:iron_sword": 250, "minecraft:iron_pickaxe": 250,
    "minecraft:stone_sword": 131, "minecraft:stone_pickaxe": 131,
    "minecraft:wooden_sword": 59, "minecraft:wooden_pickaxe": 59,
    "minecraft:diamond_helmet": 363, "minecraft:diamond_chestplate": 528,
    "minecraft:netherite_helmet": 407, "minecraft:netherite_chestplate": 592,
    "minecraft:iron_helmet": 165, "minecraft:iron_chestplate": 240,
    "minecraft:bow": 384, "minecraft:crossbow": 465, "minecraft:trident": 250,
    "minecraft:elytra": 432, "minecraft:shield": 336,
}


def _roman_numeral(n: int) -> str:
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for val, numeral in vals:
        while n >= val:
            result += numeral
            n -= val
    return result
