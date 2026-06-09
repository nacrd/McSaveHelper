"""
PlayerManager - 玩家数据管理器
负责玩家 UUID 规范化、名称解析、背包物品提取等
"""
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from nbtlib import Compound


class PlayerManager:
    """玩家数据管理器"""

    def __init__(self, log_callback: Optional[Callable] = None):
        self._log = log_callback or (lambda msg, lvl="INFO": None)
        self._player_names: Dict[str, Optional[str]] = {}
        self._usercache: Dict[str, str] = {}

    def initialize_names(self, player_files: Dict[str, Path], usercache: Dict[str, str]) -> None:
        """初始化玩家名称映射

        Args:
            player_files: UUID -> 文件路径的映射
            usercache: 从 usercache.json 加载的 UUID -> 名称映射
        """
        self._usercache = usercache

        # 初始化所有玩家的名称（先用 usercache 填充）
        for uuid in player_files:
            self._player_names[uuid] = usercache.get(uuid)

    def get_player_names(self, player_uuids: List[str]) -> Dict[str, Optional[str]]:
        """返回 UUID 到玩家名称的映射

        Args:
            player_uuids: 玩家 UUID 列表

        Returns:
            UUID -> 名称的映射（未知名称为 None）
        """
        result: Dict[str, Optional[str]] = {}
        for uuid in player_uuids:
            result[uuid] = self._player_names.get(uuid)
        return result

    def resolve_player_name(self, uuid: str, player_data: Optional[Compound]) -> Optional[str]:
        """按需解析单个玩家名称（从 NBT 加载）

        Args:
            uuid: 玩家 UUID（规范化后）
            player_data: 玩家 NBT 数据

        Returns:
            玩家名称，若无法解析则返回 None
        """
        # 如果已缓存，直接返回
        if uuid in self._player_names and self._player_names[uuid] is not None:
            return self._player_names[uuid]

        # 从 NBT 数据中提取
        if player_data is None:
            return None

        name_keys = [
            "LastKnownName", "Name", "bukkit.lastKnownName",
            "CustomName", "display.Name", "lastKnownName", "name"
        ]

        for key in name_keys:
            tag = player_data.get(key)
            if tag is not None:
                name = str(tag.value) if hasattr(tag, 'value') else str(tag)
                name = name.strip("'\"")
                self._player_names[uuid] = name
                return name

        return None

    def get_player_inventory(self, player_data: Optional[Compound]) -> List[Dict[str, Any]]:
        """提取指定玩家的背包物品列表

        Args:
            player_data: 玩家 NBT 数据

        Returns:
            物品字典列表，每项包含 slot, id, count, tag
        """
        if player_data is None:
            return []

        items: List[Dict[str, Any]] = []
        inventory = player_data.get("Inventory")

        if inventory is not None and isinstance(inventory, list):
            for slot in inventory:
                try:
                    si = slot.get("Slot", -1)
                    iid = slot.get("id", "")
                    cnt = slot.get("Count", 1)
                    tag = slot.get("tag")

                    if iid:
                        items.append({
                            "slot": int(si),
                            "id": str(iid),
                            "count": int(cnt),
                            "tag": tag,
                        })
                except Exception:
                    pass

        return items

    def import_usercache(self, path: Path, player_files: Dict[str, Path]) -> int:
        """从指定的 usercache.json 文件导入玩家名称映射

        Args:
            path: usercache.json 文件路径
            player_files: UUID -> 文件路径的映射

        Returns:
            成功导入的条目数量
        """
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)

            imported = 0
            for entry in entries:
                uuid = self.normalize_uuid(entry.get("uuid", ""))
                name = entry.get("name", "")
                if uuid and name:
                    self._usercache[uuid] = name
                    imported += 1

            self._log(f"从 {path.name} 导入了 {imported} 个玩家名称", "IMPORT")

            # 为所有在 player_files 中的 UUID 更新 player_names
            updated = 0
            for uuid in player_files.keys():
                if uuid in self._usercache:
                    old = self._player_names.get(uuid)
                    self._player_names[uuid] = self._usercache[uuid]
                    updated += 1
                    self._log(f"更新玩家名称: {uuid} -> {self._usercache[uuid]} (之前: {old})", "IMPORT")

            self._log(f"更新了 {updated} 个玩家名称", "IMPORT")
            return imported

        except Exception as e:
            self._log(f"导入 usercache.json 失败: {e}", "ERROR")
            return 0

    @staticmethod
    def normalize_uuid(uuid: str) -> str:
        """规范化 UUID：移除连字符并转为小写"""
        return uuid.replace("-", "").lower()

    @staticmethod
    def format_uuid_with_hyphens(uuid: str) -> str:
        """将规范化 UUID（32 字符）格式化为带连字符的标准形式 (8-4-4-4-12)

        Args:
            uuid: UUID 字符串

        Returns:
            格式化后的 UUID，若长度不是 32 则返回原字符串
        """
        uuid = uuid.replace("-", "").lower()
        if len(uuid) != 32:
            return uuid
        return f"{uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}"
