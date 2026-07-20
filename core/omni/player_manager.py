"""
PlayerManager - 玩家数据管理器
负责玩家 UUID 规范化、名称解析、状态/容器提取等
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from nbtlib import Compound

from core.uuid_utils import format_uuid_with_hyphens, normalize_uuid


# Inventory slot ranges used by Java Edition player.dat
MAIN_INVENTORY_SLOTS = frozenset(range(0, 36))
EQUIPMENT_SLOTS = frozenset({100, 101, 102, 103, -106})
ENDER_CHEST_SLOTS = frozenset(range(0, 27))

_NAME_KEYS = (
    "LastKnownName",
    "Name",
    "bukkit.lastKnownName",
    "CustomName",
    "display.Name",
    "lastKnownName",
    "name",
)


@dataclass(frozen=True)
class PlayerItemStack:
    """背包/末影箱/装备中的一件物品，序列化形状稳定。

    Attributes:
        slot: Java 槽位索引。
        id: 物品注册 id（如 ``minecraft:stone``）。
        count: 堆叠数量。
        tag: 旧版 NBT ``tag``（可能为 None）。
        components: 1.20.5+ components 映射（可能为 None）。
    """

    slot: int
    id: str
    count: int
    tag: Any = None
    components: Any = None

    def to_dict(self) -> Dict[str, Any]:
        """转为 UI/服务层复用的字典；缺省字段不写入。

        Returns:
            至少含 slot/id/count；有 tag/components 时一并带上。
        """
        payload: Dict[str, Any] = {
            "slot": self.slot,
            "id": self.id,
            "count": self.count,
        }
        if self.tag is not None:
            payload["tag"] = self.tag
        if self.components is not None:
            payload["components"] = self.components
        return payload


@dataclass(frozen=True)
class PlayerIdentity:
    """玩家身份：规范化 UUID、带连字符 UUID 与显示名。

    Attributes:
        uuid_norm: 32 位小写无连字符 UUID。
        uuid_hyphen: 标准 8-4-4-4-12 形式。
        name: 解析到的玩家名；未知时为 None。
    """

    uuid_norm: str
    uuid_hyphen: str
    name: Optional[str]


@dataclass(frozen=True)
class PlayerState:
    """玩家生存/模式相关状态字段（均可选，缺省为 None）。

    Attributes:
        health: 生命值。
        food_level: 饥饿值。
        food_saturation: 饱和度。
        xp_level: 经验等级。
        xp_total: 总经验。
        xp_p: 当前等级进度 (0-1)。
        air: 剩余空气。
        dimension: 所在维度 id。
        game_type: 游戏模式枚举值。
        selected_slot: 快捷栏选中槽。
        score: 分数。
    """

    health: Optional[float]
    food_level: Optional[int]
    food_saturation: Optional[float]
    xp_level: Optional[int]
    xp_total: Optional[int]
    xp_p: Optional[float]
    air: Optional[int]
    dimension: Optional[str]
    game_type: Optional[int]
    selected_slot: Optional[int]
    score: Optional[int]


@dataclass(frozen=True)
class PlayerPose:
    """玩家世界坐标与朝向。

    Attributes:
        x: 世界 X。
        y: 世界 Y。
        z: 世界 Z。
        yaw: 偏航角。
        pitch: 俯仰角。
    """

    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    yaw: Optional[float]
    pitch: Optional[float]


@dataclass(frozen=True)
class PlayerSpawn:
    """个人重生点（床/重生锚等）。

    Attributes:
        x: 方块 X。
        y: 方块 Y。
        z: 方块 Z。
        dimension: 重生维度。
        forced: 是否强制重生点。
    """

    x: Optional[int]
    y: Optional[int]
    z: Optional[int]
    dimension: Optional[str]
    forced: Optional[bool]


@dataclass(frozen=True)
class PlayerDeathLocation:
    """最近一次死亡位置。

    Attributes:
        dimension: 死亡维度。
        x: 死亡 X。
        y: 死亡 Y。
        z: 死亡 Z。
    """

    dimension: Optional[str]
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]


@dataclass(frozen=True)
class PlayerAbilities:
    """玩家 abilities 子标签（飞行/建造权限与速度）。

    Attributes:
        flying: 当前是否在飞。
        may_fly: 是否允许飞行。
        instabuild: 创造模式瞬间放置。
        invulnerable: 是否无敌。
        may_build: 是否可破坏/放置方块。
        walk_speed: 行走速度。
        fly_speed: 飞行速度。
    """

    flying: Optional[bool]
    may_fly: Optional[bool]
    instabuild: Optional[bool]
    invulnerable: Optional[bool]
    may_build: Optional[bool]
    walk_speed: Optional[float]
    fly_speed: Optional[float]


@dataclass(frozen=True)
class PlayerAttribute:
    """Attributes 列表中的一项属性。

    Attributes:
        name: 属性 id。
        base: 基础值。
        modifiers: 修饰器数量。
    """

    name: str
    base: Optional[float]
    modifiers: int = 0


@dataclass(frozen=True)
class PlayerEffect:
    """玩家身上的一个药水/状态效果。

    Attributes:
        id: 效果 id（字符串或 ``effect:N``）。
        amplifier: 放大器等级。
        duration: 剩余 tick。
        ambient: 是否环境效果。
        show_particles: 是否显示粒子。
        show_icon: 是否显示图标。
    """

    id: str
    amplifier: int
    duration: int
    ambient: bool = False
    show_particles: bool = True
    show_icon: bool = True


@dataclass(frozen=True)
class PlayerContainers:
    """按槽位范围拆分后的三类容器。

    Attributes:
        inventory: 主背包 0–35。
        equipment: 装备与副手槽。
        ender_items: 末影箱 0–26。
    """

    inventory: tuple[PlayerItemStack, ...]
    equipment: tuple[PlayerItemStack, ...]
    ender_items: tuple[PlayerItemStack, ...]


class PlayerManager:
    """玩家数据管理器。

    负责 UUID 规范化、名称缓存、从 player.dat Compound 提取状态/容器等。
    不直接读写磁盘路径以外的业务事务；加载文件由调用方完成。
    """

    def __init__(self, log_callback: Optional[Callable] = None):
        """创建管理器。

        Args:
            log_callback: 可选 ``(message, level)`` 日志回调；缺省为静默。
        """
        self._log = log_callback or (lambda msg, lvl="INFO": None)
        self._player_names: Dict[str, Optional[str]] = {}
        self._usercache: Dict[str, str] = {}

    def initialize_names(
        self,
        player_files: Dict[str, Path],
        usercache: Dict[str, str],
    ) -> None:
        """初始化玩家名称映射

        Args:
            player_files: UUID -> 文件路径的映射
            usercache: 从 usercache.json 加载的 UUID -> 名称映射
        """
        # Merge rather than replace so seeded/imported names survive.
        for uuid, name in usercache.items():
            norm = normalize_uuid(uuid)
            if not norm or not name:
                continue
            cleaned = str(name).strip()
            if not cleaned:
                continue
            self._usercache[norm] = cleaned

        for uuid in player_files:
            norm = normalize_uuid(uuid)
            if not norm:
                continue
            if norm not in self._player_names or not self._player_names[norm]:
                self._player_names[norm] = self._usercache.get(norm)

    def get_player_names(
        self,
        player_uuids: List[str],
    ) -> Dict[str, Optional[str]]:
        """返回 UUID 到玩家名称的映射（未知名称为 None）"""
        result: Dict[str, Optional[str]] = {}
        for uuid in player_uuids:
            result[uuid] = self.get_known_name(uuid)
        return result

    def get_known_name(self, uuid: str) -> Optional[str]:
        """返回缓存显示名，不加载 player NBT。

        同时查 per-player 缓存与完整 usercache，使仅有 stats 的 UUID
        仍能解析名称。

        Args:
            uuid: 任意格式的玩家 UUID。

        Returns:
            已知名称；无法解析时为 None。
        """
        norm = normalize_uuid(uuid)
        if not norm:
            return None
        cached = self._player_names.get(norm)
        if cached:
            return cached
        return self._usercache.get(norm)

    def seed_names(self, names: Dict[str, Optional[str]]) -> None:
        """合并外部 UUID -> 名称映射到缓存。

        Args:
            names: 外部提供的名称表；空名会被跳过。
        """
        for uuid, name in names.items():
            if not name:
                continue
            norm = normalize_uuid(uuid)
            if not norm:
                continue
            cleaned = str(name).strip()
            if not cleaned:
                continue
            self._player_names[norm] = cleaned
            self._usercache[norm] = cleaned

    def resolve_player_name(
        self,
        uuid: str,
        player_data: Optional[Compound],
    ) -> Optional[str]:
        """按需解析单个玩家名称（缓存优先，再读 NBT 候选键）。

        Args:
            uuid: 玩家 UUID。
            player_data: 可选 player.dat 根 Compound。

        Returns:
            解析到的名称；失败为 None。
        """
        norm = normalize_uuid(uuid)
        known = self.get_known_name(norm)
        if known:
            return known

        if player_data is None:
            return None

        for key in _NAME_KEYS:
            tag = player_data.get(key)
            if tag is None:
                continue
            name = str(tag.value) if hasattr(tag, "value") else str(tag)
            name = name.strip("'\"")
            if name:
                self._player_names[norm] = name
                self._usercache[norm] = name
                return name

        return None

    def extract_identity(
        self,
        uuid: str,
        player_data: Optional[Compound] = None,
    ) -> PlayerIdentity:
        """构建玩家身份；可选从 NBT 解析名称。

        Args:
            uuid: 玩家 UUID。
            player_data: 可选 player.dat Compound。

        Returns:
            规范化后的 ``PlayerIdentity``。
        """
        norm = normalize_uuid(uuid)
        if player_data is not None:
            name = self.resolve_player_name(norm, player_data)
        else:
            name = self.get_known_name(norm)
        return PlayerIdentity(
            uuid_norm=norm,
            uuid_hyphen=format_uuid_with_hyphens(norm),
            name=name,
        )

    def extract_state(self, player_data: Optional[Compound]) -> PlayerState:
        """从 player.dat 提取生存/模式状态。

        Args:
            player_data: player.dat 根；None 时返回全空字段。

        Returns:
            ``PlayerState`` 快照。
        """
        if player_data is None:
            return PlayerState(
                health=None,
                food_level=None,
                food_saturation=None,
                xp_level=None,
                xp_total=None,
                xp_p=None,
                air=None,
                dimension=None,
                game_type=None,
                selected_slot=None,
                score=None,
            )
        return PlayerState(
            health=_as_float(player_data.get("Health")),
            food_level=_as_int(player_data.get("foodLevel")),
            food_saturation=_as_float(player_data.get("foodSaturationLevel")),
            xp_level=_as_int(player_data.get("XpLevel")),
            xp_total=_as_int(player_data.get("XpTotal")),
            xp_p=_as_float(player_data.get("XpP")),
            air=_as_int(player_data.get("Air")),
            dimension=_as_str(player_data.get("Dimension")),
            game_type=_as_int(
                player_data.get("playerGameType", player_data.get("GameType"))
            ),
            selected_slot=_as_int(player_data.get("SelectedItemSlot")),
            score=_as_int(player_data.get("Score")),
        )

    def extract_pose(self, player_data: Optional[Compound]) -> PlayerPose:
        """提取 Pos/Rotation 坐标与朝向。

        Args:
            player_data: player.dat 根；None 时坐标全为 None。

        Returns:
            ``PlayerPose`` 快照。
        """
        if player_data is None:
            return PlayerPose(x=None, y=None, z=None, yaw=None, pitch=None)
        pos = player_data.get("Pos")
        rot = player_data.get("Rotation")
        return PlayerPose(
            x=_sequence_float(pos, 0),
            y=_sequence_float(pos, 1),
            z=_sequence_float(pos, 2),
            yaw=_sequence_float(rot, 0),
            pitch=_sequence_float(rot, 1),
        )

    def extract_spawn(self, player_data: Optional[Compound]) -> PlayerSpawn:
        """提取个人重生点字段。

        Args:
            player_data: player.dat 根。

        Returns:
            ``PlayerSpawn``；无数据时字段为 None。
        """
        if player_data is None:
            return PlayerSpawn(
                x=None, y=None, z=None, dimension=None, forced=None
            )
        return PlayerSpawn(
            x=_as_int(player_data.get("SpawnX")),
            y=_as_int(player_data.get("SpawnY")),
            z=_as_int(player_data.get("SpawnZ")),
            dimension=_as_str(player_data.get("SpawnDimension")),
            forced=_as_bool(player_data.get("SpawnForced")),
        )

    def extract_death(
        self,
        player_data: Optional[Compound],
    ) -> Optional[PlayerDeathLocation]:
        """提取 ``LastDeathLocation``；无记录时返回 None。

        Args:
            player_data: player.dat 根。

        Returns:
            死亡位置，或 None 表示从未记录。
        """
        if player_data is None:
            return None
        death = player_data.get("LastDeathLocation")
        if death is None:
            return None
        if not hasattr(death, "get"):
            return None
        pos = death.get("pos")
        return PlayerDeathLocation(
            dimension=_as_str(death.get("dimension")),
            x=_sequence_float(pos, 0),
            y=_sequence_float(pos, 1),
            z=_sequence_float(pos, 2),
        )

    def extract_abilities(
        self,
        player_data: Optional[Compound],
    ) -> PlayerAbilities:
        """提取 abilities 子 compound（飞行/建造权限等）。

        Args:
            player_data: player.dat 根。

        Returns:
            ``PlayerAbilities``；缺字段时对应项为 None。
        """
        empty = PlayerAbilities(
            flying=None,
            may_fly=None,
            instabuild=None,
            invulnerable=None,
            may_build=None,
            walk_speed=None,
            fly_speed=None,
        )
        if player_data is None:
            return empty
        abilities = player_data.get("abilities")
        if abilities is None or not hasattr(abilities, "get"):
            return empty
        return PlayerAbilities(
            flying=_as_bool(abilities.get("flying")),
            may_fly=_as_bool(abilities.get("mayfly")),
            instabuild=_as_bool(abilities.get("instabuild")),
            invulnerable=_as_bool(abilities.get("invulnerable")),
            may_build=_as_bool(abilities.get("mayBuild")),
            walk_speed=_as_float(abilities.get("walkSpeed")),
            fly_speed=_as_float(abilities.get("flySpeed")),
        )

    def extract_containers(
        self,
        player_data: Optional[Compound],
    ) -> PlayerContainers:
        """按槽位范围拆分背包、装备与末影箱。

        Args:
            player_data: player.dat 根。

        Returns:
            三类容器的不可变 tuple 集合。
        """
        if player_data is None:
            return PlayerContainers(inventory=(), equipment=(), ender_items=())

        inventory_items = _parse_item_list(player_data.get("Inventory"))
        ender_items = _parse_item_list(player_data.get("EnderItems"))

        main = tuple(
            item for item in inventory_items if item.slot in MAIN_INVENTORY_SLOTS
        )
        equipment = tuple(
            item for item in inventory_items if item.slot in EQUIPMENT_SLOTS
        )
        ender = tuple(
            item for item in ender_items if item.slot in ENDER_CHEST_SLOTS
        )
        return PlayerContainers(
            inventory=main,
            equipment=equipment,
            ender_items=ender,
        )

    def extract_attributes(
        self,
        player_data: Optional[Compound],
    ) -> tuple[PlayerAttribute, ...]:
        """提取 Attributes 列表（兼容大小写字段名）。

        Args:
            player_data: player.dat 根。

        Returns:
            ``PlayerAttribute`` 元组；无数据时为空元组。
        """
        if player_data is None:
            return ()
        raw = player_data.get("Attributes")
        if raw is None:
            return ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return ()
        results: List[PlayerAttribute] = []
        for entry in raw:
            if not hasattr(entry, "get"):
                continue
            name = _as_str(entry.get("Name", entry.get("name")))
            if not name:
                continue
            base = _as_float(entry.get("Base", entry.get("base")))
            modifiers = entry.get("Modifiers", entry.get("modifiers"))
            mod_count = 0
            if modifiers is not None and hasattr(modifiers, "__len__"):
                try:
                    mod_count = len(modifiers)
                except TypeError:
                    mod_count = 0
            results.append(
                PlayerAttribute(name=name, base=base, modifiers=mod_count)
            )
        return tuple(results)

    def extract_effects(
        self,
        player_data: Optional[Compound],
    ) -> tuple[PlayerEffect, ...]:
        """提取状态效果；兼容 pre-1.20 数字 Id 与新版字符串 id。

        Args:
            player_data: player.dat 根。

        Returns:
            ``PlayerEffect`` 元组。
        """
        if player_data is None:
            return ()
        raw = player_data.get("active_effects")
        if raw is None:
            raw = player_data.get("ActiveEffects")
        if raw is None:
            return ()
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            return ()
        results: List[PlayerEffect] = []
        for entry in raw:
            if not hasattr(entry, "get"):
                continue
            effect_id = _as_str(
                entry.get("id", entry.get("Id", entry.get("effect")))
            )
            if not effect_id:
                # Pre-1.20 numeric potion id
                numeric = _as_int(entry.get("Id", entry.get("id")))
                if numeric is None:
                    continue
                effect_id = f"effect:{numeric}"
            amplifier = _as_int(entry.get("amplifier", entry.get("Amplifier", 0)))
            duration = _as_int(entry.get("duration", entry.get("Duration", 0)))
            ambient = _as_bool(entry.get("ambient", entry.get("Ambient")))
            show_particles = _as_bool(
                entry.get("show_particles", entry.get("ShowParticles"))
            )
            show_icon = _as_bool(entry.get("show_icon", entry.get("ShowIcon")))
            results.append(
                PlayerEffect(
                    id=effect_id,
                    amplifier=amplifier if amplifier is not None else 0,
                    duration=duration if duration is not None else 0,
                    ambient=bool(ambient) if ambient is not None else False,
                    show_particles=(
                        bool(show_particles)
                        if show_particles is not None
                        else True
                    ),
                    show_icon=bool(show_icon) if show_icon is not None else True,
                )
            )
        return tuple(results)

    @staticmethod
    def extract_nested_container_items(
        item: Mapping[str, Any] | PlayerItemStack,
    ) -> List[Dict[str, Any]]:
        """提取潜影盒/收纳袋等内部物品列表。

        支持旧版 ``tag.BlockEntityTag.Items`` 与 1.20.5+
        ``components['minecraft:container']``。

        Args:
            item: ``PlayerItemStack`` 或含 tag/components 的映射。

        Returns:
            内部物品字典列表；空潜影盒返回 ``[]``，非容器返回 ``[]``。
        """
        if isinstance(item, PlayerItemStack):
            tag = item.tag
            components = item.components
            item_id = item.id
        else:
            tag = item.get("tag")
            components = item.get("components")
            item_id = str(item.get("id", "") or "")

        # Modern components container
        if components is not None:
            modern = _extract_component_container(components)
            if modern:
                return modern

        # Legacy BlockEntityTag
        if tag is not None and hasattr(tag, "get"):
            block_entity = tag.get("BlockEntityTag")
            if block_entity is not None and hasattr(block_entity, "get"):
                nested = _parse_item_list(block_entity.get("Items"))
                if nested:
                    return [entry.to_dict() for entry in nested]

        # Bundles etc. may use tag.Items directly
        if tag is not None and hasattr(tag, "get"):
            nested = _parse_item_list(tag.get("Items"))
            if nested:
                return [entry.to_dict() for entry in nested]

        # No nested payload — empty shulker still counts as openable.
        if "shulker_box" in item_id:
            return []
        return []

    @staticmethod
    def is_container_item(item_id: str) -> bool:
        """判断物品 id 是否为可打开的容器（潜影盒/收纳袋等）。

        Args:
            item_id: 物品注册 id。

        Returns:
            可打开时为 True。
        """
        text = (item_id or "").lower()
        return (
            "shulker_box" in text
            or text.endswith(":bundle")
            or text.endswith(":bundle_of")
            or "bundle" in text
        )

    def get_player_inventory(
        self,
        player_data: Optional[Compound],
    ) -> List[Dict[str, Any]]:
        """提取指定玩家的背包物品列表（含装备槽，兼容旧调用方）

        Returns:
            物品字典列表，每项包含 slot, id, count, 以及可选 tag/components
        """
        if player_data is None:
            return []
        items = _parse_item_list(player_data.get("Inventory"))
        return [item.to_dict() for item in items]

    def get_player_ender_items(
        self,
        player_data: Optional[Compound],
    ) -> List[Dict[str, Any]]:
        """提取末影箱物品列表（字典形式，供 UI 复用）。"""
        if player_data is None:
            return []
        items = _parse_item_list(player_data.get("EnderItems"))
        return [
            item.to_dict()
            for item in items
            if item.slot in ENDER_CHEST_SLOTS
        ]

    def import_usercache(
        self,
        path: Path,
        player_files: Dict[str, Path],
    ) -> int:
        """从指定的 usercache.json 文件导入玩家名称映射"""
        try:
            import json

            with open(path, "r", encoding="utf-8") as handle:
                entries = json.load(handle)

            imported = 0
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                uuid = normalize_uuid(str(entry.get("uuid", "") or ""))
                name = str(entry.get("name", "") or "").strip()
                if uuid and name:
                    self._usercache[uuid] = name
                    imported += 1

            self._log(f"从 {path.name} 导入了 {imported} 个玩家名称", "IMPORT")

            updated = 0
            for uuid in player_files.keys():
                norm = normalize_uuid(uuid)
                if norm and norm in self._usercache:
                    old = self._player_names.get(norm)
                    self._player_names[norm] = self._usercache[norm]
                    updated += 1
                    self._log(
                        f"更新玩家名称: {norm} -> {self._usercache[norm]} "
                        f"(之前: {old})",
                        "IMPORT",
                    )

            self._log(f"更新了 {updated} 个玩家名称", "IMPORT")
            return imported

        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._log(f"导入 usercache.json 失败: {exc}", "ERROR")
            return 0
        except Exception as exc:
            self._log(f"导入 usercache.json 失败: {exc}", "ERROR")
            return 0

    @staticmethod
    def normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return normalize_uuid(uuid)

    @staticmethod
    def format_uuid_with_hyphens(uuid: str) -> str:
        """将规范化 UUID（32 字符）格式化为带连字符的标准形式 (8-4-4-4-12)"""
        return format_uuid_with_hyphens(uuid)


def _parse_item_list(raw: Any) -> List[PlayerItemStack]:
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []

    items: List[PlayerItemStack] = []
    for slot in raw:
        try:
            if not hasattr(slot, "get"):
                continue
            item_id = _as_str(slot.get("id"))
            if not item_id:
                continue
            slot_index = _as_int(slot.get("Slot", slot.get("slot", -1)))
            if slot_index is None:
                slot_index = -1
            count = _as_int(slot.get("Count", slot.get("count", 1)))
            if count is None:
                count = 1
            tag = slot.get("tag")
            components = slot.get("components")
            items.append(
                PlayerItemStack(
                    slot=slot_index,
                    id=item_id,
                    count=count,
                    tag=tag,
                    components=components,
                )
            )
        except (TypeError, ValueError, AttributeError, KeyError):
            continue
    return items


def _mapping_get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    try:
        if hasattr(obj, "get"):
            return obj.get(key, default)
        if isinstance(obj, Mapping):
            return obj.get(key, default)
    except (TypeError, KeyError):
        return default
    return default


def _extract_component_container(components: Any) -> List[Dict[str, Any]]:
    """Parse ``minecraft:container`` component into item dicts."""
    raw = _mapping_get(components, "minecraft:container")
    if raw is None:
        raw = _mapping_get(components, "container")
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []

    results: List[Dict[str, Any]] = []
    for entry in raw:
        parsed = _parse_container_entry(entry)
        if parsed is not None:
            results.append(parsed)
    return results


def _parse_container_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not hasattr(entry, "get"):
        return None
    slot_index = _as_int(entry.get("slot", -1))
    if slot_index is None:
        slot_index = -1
    nested_item = entry.get("item")
    if nested_item is None or not hasattr(nested_item, "get"):
        nested_item = entry
    item_id = _as_str(nested_item.get("id"))
    if not item_id:
        return None
    count = _as_int(nested_item.get("count", nested_item.get("Count", 1)))
    if count is None:
        count = 1
    payload: Dict[str, Any] = {
        "slot": slot_index,
        "id": item_id,
        "count": count,
    }
    tag = nested_item.get("tag")
    comps = nested_item.get("components")
    if tag is not None:
        payload["tag"] = tag
    if comps is not None:
        payload["components"] = comps
    return payload


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        try:
            text = str(value.value)
        except (AttributeError, TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = text.strip().strip("'\"")
    return text or None


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        # nbtlib Byte tags often act as 0/1
        return bool(int(value))
    except (TypeError, ValueError):
        return None


def _sequence_float(sequence: Any, index: int) -> Optional[float]:
    if sequence is None:
        return None
    try:
        if len(sequence) <= index:
            return None
        return float(sequence[index])
    except (TypeError, ValueError, IndexError):
        return None
