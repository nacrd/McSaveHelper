"""物品服务 - 处理物品名称映射和属性解析"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ItemInfo:
    """物品信息"""
    id: str
    display_name: str
    count: int = 1
    damage: Optional[int] = None
    max_damage: Optional[int] = None
    durability_percent: Optional[float] = None
    enchantments: List[Dict[str, Any]] = None
    custom_name: Optional[str] = None
    lore: List[str] = None
    slot: int = -1

    def __post_init__(self):
        if self.enchantments is None:
            self.enchantments = []
        if self.lore is None:
            self.lore = []


# 原版物品名称映射（常用物品，避免依赖外部文件）
_VANILLA_ITEM_NAMES: Dict[str, str] = {
    # 矿物与材料
    "minecraft:diamond": "钻石",
    "minecraft:iron_ingot": "铁锭",
    "minecraft:gold_ingot": "金锭",
    "minecraft:coal": "煤炭",
    "minecraft:emerald": "绿宝石",
    "minecraft:lapis_lazuli": "青金石",
    "minecraft:redstone": "红石",
    "minecraft:netherite_ingot": "下界合金锭",
    "minecraft:copper_ingot": "铜锭",
    "minecraft:amethyst_shard": "紫水晶碎片",
    "minecraft:quartz": "下界石英",
    "minecraft:glowstone_dust": "荧石粉",
    "minecraft:gunpowder": "火药",
    "minecraft:string": "线",
    "minecraft:feather": "羽毛",
    "minecraft:flint": "燧石",
    "minecraft:clay_ball": "粘土球",
    "minecraft:brick": "红砖",
    "minecraft:prismarine_shard": "海晶碎片",
    "minecraft:prismarine_crystals": "海晶灯碎片",
    "minecraft:nautilus_shell": "鹦鹉螺壳",
    "minecraft:heart_of_the_sea": "海洋之心",
    "minecraft:shulker_shell": "潜影壳",
    "minecraft:phantom_membrane": "幻翼膜",
    "minecraft:blaze_rod": "烈焰棒",
    "minecraft:blaze_powder": "烈焰粉",
    "minecraft:ender_pearl": "末影珍珠",
    "minecraft:ender_eye": "末影之眼",
    "minecraft:ghast_tear": "恶魂之泪",
    "minecraft:magma_cream": "岩浆膏",
    "minecraft:nether_star": "下界之星",
    "minecraft:totem_of_undying": "不死图腾",
    "minecraft:elytra": "鞘翅",
    "minecraft:trident": "三叉戟",
    "minecraft:crossbow": "弩",
    "minecraft:bow": "弓",
    "minecraft:arrow": "箭",
    # 工具
    "minecraft:diamond_sword": "钻石剑",
    "minecraft:diamond_pickaxe": "钻石镐",
    "minecraft:diamond_axe": "钻石斧",
    "minecraft:diamond_shovel": "钻石锹",
    "minecraft:diamond_hoe": "钻石锄",
    "minecraft:iron_sword": "铁剑",
    "minecraft:iron_pickaxe": "铁镐",
    "minecraft:iron_axe": "铁斧",
    "minecraft:iron_shovel": "铁锹",
    "minecraft:iron_hoe": "铁锄",
    "minecraft:golden_sword": "金剑",
    "minecraft:golden_pickaxe": "金镐",
    "minecraft:golden_axe": "金斧",
    "minecraft:golden_shovel": "金锹",
    "minecraft:golden_hoe": "金锄",
    "minecraft:stone_sword": "石剑",
    "minecraft:stone_pickaxe": "石镐",
    "minecraft:stone_axe": "石斧",
    "minecraft:stone_shovel": "石锹",
    "minecraft:stone_hoe": "石锄",
    "minecraft:wooden_sword": "木剑",
    "minecraft:wooden_pickaxe": "木镐",
    "minecraft:wooden_axe": "木斧",
    "minecraft:wooden_shovel": "木锹",
    "minecraft:wooden_hoe": "木锄",
    "minecraft:netherite_sword": "下界合金剑",
    "minecraft:netherite_pickaxe": "下界合金镐",
    "minecraft:netherite_axe": "下界合金斧",
    "minecraft:netherite_shovel": "下界合金锹",
    "minecraft:netherite_hoe": "下界合金锄",
    "minecraft:shears": "剪刀",
    "minecraft:flint_and_steel": "打火石",
    "minecraft:fishing_rod": "钓鱼竿",
    "minecraft:carrot_on_a_stick": "胡萝卜钓竿",
    "minecraft:warped_fungus_on_a_stick": "诡异菌钓竿",
    "minecraft:brush": "刷子",
    # 盔甲
    "minecraft:diamond_helmet": "钻石头盔",
    "minecraft:diamond_chestplate": "钻石胸甲",
    "minecraft:diamond_leggings": "钻石护腿",
    "minecraft:diamond_boots": "钻石靴子",
    "minecraft:iron_helmet": "铁头盔",
    "minecraft:iron_chestplate": "铁胸甲",
    "minecraft:iron_leggings": "铁护腿",
    "minecraft:iron_boots": "铁靴子",
    "minecraft:golden_helmet": "金头盔",
    "minecraft:golden_chestplate": "金胸甲",
    "minecraft:golden_leggings": "金护腿",
    "minecraft:golden_boots": "金靴子",
    "minecraft:leather_helmet": "皮革帽子",
    "minecraft:leather_chestplate": "皮革外套",
    "minecraft:leather_leggings": "皮革裤子",
    "minecraft:leather_boots": "皮革靴子",
    "minecraft:chainmail_helmet": "锁链头盔",
    "minecraft:chainmail_chestplate": "锁链胸甲",
    "minecraft:chainmail_leggings": "锁链护腿",
    "minecraft:chainmail_boots": "锁链靴子",
    "minecraft:netherite_helmet": "下界合金头盔",
    "minecraft:netherite_chestplate": "下界合金胸甲",
    "minecraft:netherite_leggings": "下界合金护腿",
    "minecraft:netherite_boots": "下界合金靴子",
    "minecraft:turtle_helmet": "海龟壳",
    # 食物
    "minecraft:apple": "苹果",
    "minecraft:bread": "面包",
    "minecraft:cooked_beef": "牛排",
    "minecraft:cooked_porkchop": "熟猪排",
    "minecraft:cooked_chicken": "熟鸡肉",
    "minecraft:cooked_mutton": "熟羊肉",
    "minecraft:cooked_salmon": "熟鲑鱼",
    "minecraft:cooked_cod": "熟鳕鱼",
    "minecraft:golden_apple": "金苹果",
    "minecraft:enchanted_golden_apple": "附魔金苹果",
    "minecraft:golden_carrot": "金胡萝卜",
    "minecraft:baked_potato": "烤马铃薯",
    "minecraft:mushroom_stew": "蘑菇煲",
    "minecraft:beetroot_soup": "甜菜汤",
    "minecraft:rabbit_stew": "兔肉煲",
    "minecraft:pumpkin_pie": "南瓜派",
    "minecraft:cake": "蛋糕",
    "minecraft:cookie": "饼干",
    "minecraft:melon_slice": "西瓜片",
    "minecraft:sweet_berries": "甜浆果",
    "minecraft:glow_berries": "发光浆果",
    "minecraft:dried_kelp": "干海带",
    "minecraft:honey_bottle": "蜂蜜瓶",
    # 方块
    "minecraft:dirt": "泥土",
    "minecraft:grass_block": "草方块",
    "minecraft:stone": "石头",
    "minecraft:cobblestone": "圆石",
    "minecraft:oak_log": "橡木原木",
    "minecraft:spruce_log": "云杉原木",
    "minecraft:birch_log": "白桦原木",
    "minecraft:jungle_log": "丛林原木",
    "minecraft:acacia_log": "金合欢原木",
    "minecraft:dark_oak_log": "深色橡木原木",
    "minecraft:oak_planks": "橡木木板",
    "minecraft:glass": "玻璃",
    "minecraft:sand": "沙子",
    "minecraft:gravel": "砂砾",
    "minecraft:obsidian": "黑曜石",
    "minecraft:crying_obsidian": "哭泣的黑曜石",
    "minecraft:bedrock": "基岩",
    "minecraft:crafting_table": "工作台",
    "minecraft:furnace": "熔炉",
    "minecraft:chest": "箱子",
    "minecraft:ender_chest": "末影箱",
    "minecraft:shulker_box": "潜影盒",
    "minecraft:beacon": "信标",
    "minecraft:anvil": "铁砧",
    "minecraft:enchanting_table": "附魔台",
    "minecraft:brewing_stand": "酿造台",
    "minecraft:cauldron": "炼药锅",
    "minecraft:torch": "火把",
    "minecraft:soul_torch": "灵魂火把",
    "minecraft:redstone_torch": "红石火把",
    "minecraft:lantern": "灯笼",
    "minecraft:soul_lantern": "灵魂灯笼",
    # 矿石
    "minecraft:diamond_ore": "钻石矿石",
    "minecraft:iron_ore": "铁矿石",
    "minecraft:gold_ore": "金矿石",
    "minecraft:coal_ore": "煤矿石",
    "minecraft:emerald_ore": "绿宝石矿石",
    "minecraft:lapis_ore": "青金石矿石",
    "minecraft:redstone_ore": "红石矿石",
    "minecraft:copper_ore": "铜矿石",
    "minecraft:nether_gold_ore": "下界金矿石",
    "minecraft:nether_quartz_ore": "下界石英矿石",
    "minecraft:ancient_debris": "远古残骸",
    # 深板岩矿石
    "minecraft:deepslate_diamond_ore": "深板岩钻石矿石",
    "minecraft:deepslate_iron_ore": "深板岩铁矿石",
    "minecraft:deepslate_gold_ore": "深板岩金矿石",
    "minecraft:deepslate_coal_ore": "深板岩煤矿石",
    "minecraft:deepslate_emerald_ore": "深板岩绿宝石矿石",
    "minecraft:deepslate_lapis_ore": "深板岩青金石矿石",
    "minecraft:deepslate_redstone_ore": "深板岩红石矿石",
    "minecraft:deepslate_copper_ore": "深板岩铜矿石",
    # 杂项
    "minecraft:experience_bottle": "附魔之瓶",
    "minecraft:firework_rocket": "烟花火箭",
    "minecraft:firework_star": "烟花之星",
    "minecraft:writable_book": "书与笔",
    "minecraft:written_book": "成书",
    "minecraft:map": "空地图",
    "minecraft:filled_map": "地图",
    "minecraft:compass": "指南针",
    "minecraft:recovery_compass": "恢复指南针",
    "minecraft:clock": "时钟",
    "minecraft:spyglass": "望远镜",
    "minecraft:saddle": "鞍",
    "minecraft:lead": "拴绳",
    "minecraft:name_tag": "命名牌",
    "minecraft:minecart": "矿车",
    "minecraft:chest_minecart": "运输矿车",
    "minecraft:furnace_minecart": "动力矿车",
    "minecraft:tnt_minecart": "TNT矿车",
    "minecraft:hopper_minecart": "漏斗矿车",
    "minecraft:boat": "橡木船",
    "minecraft:oak_boat": "橡木船",
    "minecraft:spruce_boat": "云杉木船",
    "minecraft:birch_boat": "白桦木船",
    "minecraft:jungle_boat": "丛林木船",
    "minecraft:acacia_boat": "金合欢木船",
    "minecraft:dark_oak_boat": "深色橡木船",
    # 附魔书
    "minecraft:enchanted_book": "附魔书",
    # 药水
    "minecraft:potion": "药水",
    "minecraft:splash_potion": "喷溅药水",
    "minecraft:lingering_potion": "滞留药水",
    # 旗帜
    "minecraft:white_banner": "白色旗帜",
    "minecraft:orange_banner": "橙色旗帜",
    "minecraft:magenta_banner": "品红色旗帜",
    "minecraft:light_blue_banner": "淡蓝色旗帜",
    "minecraft:yellow_banner": "黄色旗帜",
    "minecraft:lime_banner": "黄绿色旗帜",
    "minecraft:pink_banner": "粉红色旗帜",
    "minecraft:gray_banner": "灰色旗帜",
    "minecraft:light_gray_banner": "淡灰色旗帜",
    "minecraft:cyan_banner": "青色旗帜",
    "minecraft:purple_banner": "紫色旗帜",
    "minecraft:blue_banner": "蓝色旗帜",
    "minecraft:brown_banner": "棕色旗帜",
    "minecraft:green_banner": "绿色旗帜",
    "minecraft:red_banner": "红色旗帜",
    "minecraft:black_banner": "黑色旗帜",
    # 唱片
    "minecraft:music_disc_13": "音乐唱片",
    "minecraft:music_disc_cat": "音乐唱片",
    "minecraft:music_disc_blocks": "音乐唱片",
    "minecraft:music_disc_chirp": "音乐唱片",
    "minecraft:music_disc_far": "音乐唱片",
    "minecraft:music_disc_mall": "音乐唱片",
    "minecraft:music_disc_mellohi": "音乐唱片",
    "minecraft:music_disc_stal": "音乐唱片",
    "minecraft:music_disc_strad": "音乐唱片",
    "minecraft:music_disc_ward": "音乐唱片",
    "minecraft:music_disc_11": "音乐唱片",
    "minecraft:music_disc_wait": "音乐唱片",
    "minecraft:music_disc_otherside": "音乐唱片",
    "minecraft:music_disc_5": "音乐唱片",
    "minecraft:music_disc_pigstep": "音乐唱片",
    "minecraft:music_disc_relic": "音乐唱片",
}

# 常用附魔名称映射
_ENCHANTMENT_NAMES: Dict[str, str] = {
    "minecraft:protection": "保护",
    "minecraft:fire_protection": "火焰保护",
    "minecraft:feather_falling": "摔落保护",
    "minecraft:blast_protection": "爆炸保护",
    "minecraft:projectile_protection": "弹射物保护",
    "minecraft:respiration": "水下呼吸",
    "minecraft:aqua_affinity": "水下速掘",
    "minecraft:thorns": "荆棘",
    "minecraft:depth_strider": "深海探索者",
    "minecraft:frost_walker": "冰霜行者",
    "minecraft:binding_curse": "绑定诅咒",
    "minecraft:soul_speed": "灵魂疾行",
    "minecraft:swift_sneak": "迅速潜行",
    "minecraft:sharpness": "锋利",
    "minecraft:smite": "亡灵杀手",
    "minecraft:bane_of_arthropods": "节肢杀手",
    "minecraft:knockback": "击退",
    "minecraft:fire_aspect": "火焰附加",
    "minecraft:looting": "抢夺",
    "minecraft:sweeping": "横扫之刃",
    "minecraft:efficiency": "效率",
    "minecraft:silk_touch": "精准采集",
    "minecraft:fortune": "时运",
    "minecraft:power": "力量",
    "minecraft:punch": "冲击",
    "minecraft:flame": "火矢",
    "minecraft:infinity": "无限",
    "minecraft:luck_of_the_sea": "海之眷顾",
    "minecraft:lure": "饵钓",
    "minecraft:loyalty": "忠诚",
    "minecraft:impaling": "穿刺",
    "minecraft:riptide": "激流",
    "minecraft:channeling": "引雷",
    "minecraft:multishot": "多重射击",
    "minecraft:quick_charge": "快速装填",
    "minecraft:piercing": "穿透",
    "minecraft:mending": "经验修补",
    "minecraft:vanishing_curse": "消失诅咒",
    "minecraft:unbreaking": "耐久",
}

# 常用最大耐久度
_MAX_DURABILITY: Dict[str, int] = {
    "minecraft:wooden_sword": 59,
    "minecraft:wooden_pickaxe": 59,
    "minecraft:wooden_axe": 59,
    "minecraft:wooden_shovel": 59,
    "minecraft:wooden_hoe": 59,
    "minecraft:stone_sword": 131,
    "minecraft:stone_pickaxe": 131,
    "minecraft:stone_axe": 131,
    "minecraft:stone_shovel": 131,
    "minecraft:stone_hoe": 131,
    "minecraft:iron_sword": 250,
    "minecraft:iron_pickaxe": 250,
    "minecraft:iron_axe": 250,
    "minecraft:iron_shovel": 250,
    "minecraft:iron_hoe": 250,
    "minecraft:golden_sword": 32,
    "minecraft:golden_pickaxe": 32,
    "minecraft:golden_axe": 32,
    "minecraft:golden_shovel": 32,
    "minecraft:golden_hoe": 32,
    "minecraft:diamond_sword": 1561,
    "minecraft:diamond_pickaxe": 1561,
    "minecraft:diamond_axe": 1561,
    "minecraft:diamond_shovel": 1561,
    "minecraft:diamond_hoe": 1561,
    "minecraft:netherite_sword": 2031,
    "minecraft:netherite_pickaxe": 2031,
    "minecraft:netherite_axe": 2031,
    "minecraft:netherite_shovel": 2031,
    "minecraft:netherite_hoe": 2031,
    "minecraft:leather_helmet": 55,
    "minecraft:leather_chestplate": 80,
    "minecraft:leather_leggings": 75,
    "minecraft:leather_boots": 65,
    "minecraft:chainmail_helmet": 165,
    "minecraft:chainmail_chestplate": 240,
    "minecraft:chainmail_leggings": 225,
    "minecraft:chainmail_boots": 195,
    "minecraft:iron_helmet": 165,
    "minecraft:iron_chestplate": 240,
    "minecraft:iron_leggings": 225,
    "minecraft:iron_boots": 195,
    "minecraft:golden_helmet": 77,
    "minecraft:golden_chestplate": 112,
    "minecraft:golden_leggings": 105,
    "minecraft:golden_boots": 91,
    "minecraft:diamond_helmet": 363,
    "minecraft:diamond_chestplate": 528,
    "minecraft:diamond_leggings": 495,
    "minecraft:diamond_boots": 429,
    "minecraft:netherite_helmet": 407,
    "minecraft:netherite_chestplate": 592,
    "minecraft:netherite_leggings": 555,
    "minecraft:netherite_boots": 481,
    "minecraft:turtle_helmet": 275,
    "minecraft:elytra": 432,
    "minecraft:trident": 250,
    "minecraft:bow": 384,
    "minecraft:crossbow": 465,
    "minecraft:fishing_rod": 64,
    "minecraft:shears": 238,
    "minecraft:flint_and_steel": 64,
    "minecraft:carrot_on_a_stick": 25,
    "minecraft:warped_fungus_on_a_stick": 100,
    "minecraft:shield": 336,
    "minecraft:brush": 64,
    "minecraft:spyglass": None,
}


class ItemService:
    """物品服务 - 处理物品名称映射和属性解析"""

    _instance: Optional['ItemService'] = None

    def __new__(cls) -> 'ItemService':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """初始化内部状态"""
        self._name_map: Dict[str, str] = _VANILLA_ITEM_NAMES.copy()
        self._enchantment_names: Dict[str, str] = _ENCHANTMENT_NAMES.copy()
        self._max_durability: Dict[str, int] = _MAX_DURABILITY.copy()
        self._custom_slots: Dict[int, str] = {}

    def load_language_file(self, path: Path, namespace: str = "minecraft") -> int:
        """
        加载 Minecraft 语言文件（JSON 格式）

        Minecraft 语言文件格式: {"item.minecraft.diamond": "Diamond", ...}
        也支持直接格式: {"minecraft:diamond": "钻石", ...}

        Args:
            path: 语言文件路径
            namespace: 命名空间前缀

        Returns:
            成功加载的条目数量
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            count = 0
            for key, value in data.items():
                if not isinstance(value, str):
                    continue

                # 格式1: item.minecraft.diamond -> minecraft:diamond
                if key.startswith("item."):
                    parts = key.split(".")
                    if len(parts) >= 3:
                        ns = parts[1] if len(parts) > 2 else namespace
                        item_id = ":".join(parts[2:])
                        full_id = f"{ns}:{item_id}"
                        self._name_map[full_id] = value
                        count += 1

                # 格式2: block.minecraft.dirt -> minecraft:dirt
                elif key.startswith("block."):
                    parts = key.split(".")
                    if len(parts) >= 3:
                        ns = parts[1] if len(parts) > 2 else namespace
                        item_id = ":".join(parts[2:])
                        full_id = f"{ns}:{item_id}"
                        self._name_map[full_id] = value
                        count += 1

                # 格式3: 直接 ID 格式 "minecraft:diamond": "钻石"
                elif ":" in key:
                    self._name_map[key] = value
                    count += 1

                # 格式4: enchantment.minecraft.sharpness -> sharpness
                elif key.startswith("enchantment."):
                    parts = key.split(".")
                    if len(parts) >= 3:
                        ench_id = f"minecraft:{parts[-1]}"
                        self._enchantment_names[ench_id] = value
                        count += 1

            return count
        except Exception as e:
            return 0

    def get_item_name(self, item_id: str) -> str:
        """
        获取物品显示名称

        Args:
            item_id: 物品ID，如 "minecraft:diamond"

        Returns:
            显示名称，如果没有映射则返回简化后的ID
        """
        if item_id in self._name_map:
            return self._name_map[item_id]

        # 尝试去掉命名空间
        if ":" in item_id:
            _, local_id = item_id.split(":", 1)
            return local_id.replace("_", " ").title()

        return item_id

    def get_enchantment_name(self, ench_id: str) -> str:
        """获取附魔名称"""
        if ench_id in self._enchantment_names:
            return self._enchantment_names[ench_id]
        if ":" in ench_id:
            _, local_id = ench_id.split(":", 1)
            return local_id.replace("_", " ").title()
        return ench_id

    def parse_item(self, item_data: Dict[str, Any]) -> ItemInfo:
        """
        解析物品数据，提取完整信息

        Args:
            item_data: 物品数据字典，包含 slot, id, count, tag

        Returns:
            ItemInfo 对象
        """
        item_id = item_data.get("id", "")
        count = item_data.get("count", 1)
        slot = item_data.get("slot", -1)
        tag = item_data.get("tag")

        display_name = self.get_item_name(item_id)
        max_dur = self._max_durability.get(item_id)

        damage = None
        durability_percent = None
        enchantments = []
        custom_name = None
        lore = []

        if tag is not None:
            try:
                # 解析自定义名称
                display_tag = tag.get("display")
                if display_tag and hasattr(display_tag, 'get'):
                    name_tag = display_tag.get("Name")
                    if name_tag:
                        custom_name = str(name_tag)
                        display_name = custom_name

                    lore_tag = display_tag.get("Lore")
                    if lore_tag and hasattr(lore_tag, '__iter__'):
                        lore = [str(line) for line in lore_tag]

                # 解析耐久度
                damage_tag = tag.get("Damage")
                if damage_tag is not None:
                    damage = int(damage_tag)
                    if max_dur is not None and max_dur > 0:
                        remaining = max_dur - damage
                        durability_percent = max(0, min(100, (remaining / max_dur) * 100))

                # 解析附魔
                ench_tag = tag.get("Enchantments")
                if ench_tag and hasattr(ench_tag, '__iter__'):
                    for ench in ench_tag:
                        if hasattr(ench, 'get'):
                            ench_id = str(ench.get("id", ""))
                            ench_level = int(ench.get("lvl", 1))
                            ench_name = self.get_enchantment_name(ench_id)
                            enchantments.append({
                                "id": ench_id,
                                "name": ench_name,
                                "level": ench_level,
                            })

                # 也检查 StoredEnchantments（附魔书）
                stored_ench = tag.get("StoredEnchantments")
                if stored_ench and hasattr(stored_ench, '__iter__'):
                    for ench in stored_ench:
                        if hasattr(ench, 'get'):
                            ench_id = str(ench.get("id", ""))
                            ench_level = int(ench.get("lvl", 1))
                            ench_name = self.get_enchantment_name(ench_id)
                            enchantments.append({
                                "id": ench_id,
                                "name": ench_name,
                                "level": ench_level,
                            })
            except Exception:
                pass

        return ItemInfo(
            id=item_id,
            display_name=display_name,
            count=count,
            damage=damage,
            max_damage=max_dur,
            durability_percent=durability_percent,
            enchantments=enchantments,
            custom_name=custom_name,
            lore=lore,
            slot=slot,
        )

    def register_custom_slot(self, slot_id: int, name: str) -> None:
        """注册自定义装备槽位"""
        self._custom_slots[slot_id] = name

    def get_custom_slots(self) -> Dict[int, str]:
        """获取所有自定义槽位"""
        return self._custom_slots.copy()

    def format_item_tooltip(self, item_info: ItemInfo) -> str:
        """格式化物品提示信息"""
        lines = [item_info.display_name]

        if item_info.custom_name:
            lines.append(f"ID: {item_info.id}")

        if item_info.count > 1:
            lines.append(f"数量: {item_info.count}")

        if item_info.durability_percent is not None:
            bar_len = 10
            filled = int(item_info.durability_percent / 100 * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"耐久: {bar} {item_info.durability_percent:.0f}%")
            if item_info.damage is not None and item_info.max_damage is not None:
                lines.append(f"  ({item_info.max_damage - item_info.damage}/{item_info.max_damage})")

        if item_info.enchantments:
            lines.append("附魔:")
            for ench in item_info.enchantments:
                level_str = _roman_numeral(ench["level"])
                lines.append(f"  {ench['name']} {level_str}")

        if item_info.lore:
            for lore_line in item_info.lore:
                lines.append(f"§o{lore_line}§r")

        return "\n".join(lines)


def _roman_numeral(n: int) -> str:
    """将数字转换为罗马数字（用于附魔等级显示）"""
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    result = ""
    for val, numeral in vals:
        while n >= val:
            result += numeral
            n -= val
    return result


def get_item_service() -> ItemService:
    """获取物品服务单例"""
    return ItemService()