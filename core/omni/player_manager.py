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
    """One inventory / ender / equipment stack with a stable dict shape."""

    slot: int
    id: str
    count: int
    tag: Any = None
    components: Any = None

    def to_dict(self) -> Dict[str, Any]:
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
    uuid_norm: str
    uuid_hyphen: str
    name: Optional[str]


@dataclass(frozen=True)
class PlayerState:
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
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    yaw: Optional[float]
    pitch: Optional[float]


@dataclass(frozen=True)
class PlayerSpawn:
    x: Optional[int]
    y: Optional[int]
    z: Optional[int]
    dimension: Optional[str]
    forced: Optional[bool]


@dataclass(frozen=True)
class PlayerDeathLocation:
    dimension: Optional[str]
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]


@dataclass(frozen=True)
class PlayerAbilities:
    flying: Optional[bool]
    may_fly: Optional[bool]
    instabuild: Optional[bool]
    invulnerable: Optional[bool]
    may_build: Optional[bool]
    walk_speed: Optional[float]
    fly_speed: Optional[float]


@dataclass(frozen=True)
class PlayerContainers:
    inventory: tuple[PlayerItemStack, ...]
    equipment: tuple[PlayerItemStack, ...]
    ender_items: tuple[PlayerItemStack, ...]


class PlayerManager:
    """玩家数据管理器"""

    def __init__(self, log_callback: Optional[Callable] = None):
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
        """Return a cached display name without loading player NBT.

        Looks up both the per-player cache and the full usercache map so
        stats-only UUIDs can still resolve to a name.
        """
        norm = normalize_uuid(uuid)
        if not norm:
            return None
        cached = self._player_names.get(norm)
        if cached:
            return cached
        return self._usercache.get(norm)

    def seed_names(self, names: Dict[str, Optional[str]]) -> None:
        """Merge an external UUID -> name mapping into the cache."""
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
        """按需解析单个玩家名称（从 NBT 加载）"""
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
        """Build identity for a UUID, optionally resolving name from NBT."""
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
        except Exception:
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
