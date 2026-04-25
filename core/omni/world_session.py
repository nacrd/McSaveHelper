"""
存档会话管理 (WorldSession)

实现非破坏性、延迟加载机制，支持任务队列与统一提交。
"""
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable, Union
from dataclasses import dataclass, field
import nbtlib
from nbtlib import Compound, Long, IntArray, String, File
from ..scanner import scan_all_regions
from ..types import LogCallback, ProgressCallback, NBTTag
from ..utils import update_server_properties
from ..converter import convert_endian, IdMapping, VersionDowngrader


@dataclass
class WorldInfo:
    """从 level.dat 提取的基础信息"""
    version: int
    version_name: Optional[str] = None
    game_type: Optional[int] = None
    last_played: Optional[int] = None
    spawn_x: Optional[int] = None
    spawn_y: Optional[int] = None
    spawn_z: Optional[int] = None
    level_name: Optional[str] = None


@dataclass
class Action:
    """代表一个待执行的操作"""
    type: str  # 'modify_nbt', 'delete_region', 'rename_player', 'custom'
    target: Any  # 文件路径、坐标、UUID 等
    data: Any = None
    callback: Optional[Callable] = None


class WorldSession:
    """存档会话管理器，提供延迟加载与任务队列"""

    def __init__(self, world_path: Path, log: Optional[LogCallback] = None) -> None:
        """
        初始化会话，仅读取基础信息并扫描目录结构。

        Args:
            world_path: 源世界存档路径
            log: 日志回调函数，接受 (消息, 级别) 参数
        """
        self.world_path = world_path.resolve()
        self.log = log or (lambda msg, lvl="INFO": None)
        self._world_info: Optional[WorldInfo] = None
        self._player_files: Dict[str, Path] = {}          # UUID -> 文件路径
        self._region_files: Dict[Tuple[int, int], Path] = {}  # (x, z) -> 文件路径
        self._data_files: List[Path] = []
        self._action_queue: List[Action] = []
        self._loaded_player_data: Dict[str, Compound] = {}
        self._loaded_regions: Dict[Tuple[int, int], Path] = {}
        self._level_data: Optional[File] = None
        self._player_names: Dict[str, Optional[str]] = {}
        self._usercache: Dict[str, str] = {}

        self._scan_files()
        self._load_level_info()

    def _log(self, message: str, level: str = "INFO") -> None:
        """内部日志记录"""
        if self.log:
            self.log(message, level)

    def _normalize_uuid(self, uuid: str) -> str:
        """
        规范化 UUID：移除连字符并转为小写。
        """
        return uuid.replace("-", "").lower()

    def _format_uuid_with_hyphens(self, uuid: str) -> str:
        """
        将规范化 UUID（32 字符）格式化为带连字符的标准形式 (8-4-4-4-12)。
        如果长度不是 32，返回原字符串。
        """
        uuid = uuid.replace("-", "").lower()
        if len(uuid) != 32:
            return uuid
        return f"{uuid[:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:]}"

    def _scan_files(self) -> None:
        """扫描存档目录结构，缓存文件路径"""
        # 扫描 playerdata
        playerdata_dir = self.world_path / "playerdata"
        if playerdata_dir.exists():
            for f in playerdata_dir.glob("*.dat"):
                uuid = self._normalize_uuid(f.stem)
                self._player_files[uuid] = f
        self._log(f"发现 {len(self._player_files)} 个玩家数据文件", "SCAN")

        # 扫描 region 文件
        region_files = scan_all_regions(self.world_path)
        for f in region_files:
            # 解析文件名 r.x.z.mca
            if f.stem.startswith("r."):
                parts = f.stem.split(".")
                if len(parts) == 3:
                    try:
                        x, z = int(parts[1]), int(parts[2])
                        self._region_files[(x, z)] = f
                    except ValueError:
                        pass
        self._log(f"发现 {len(self._region_files)} 个区域文件", "SCAN")

        # 扫描 data 目录
        data_dir = self.world_path / "data"
        if data_dir.exists():
            self._data_files = list(data_dir.glob("*.dat"))
        self._log(f"发现 {len(self._data_files)} 个数据文件", "SCAN")
        
        # 扫描 usercache.json（如果存在）
        # 扫描 usercache.json（如果存在）
        possible_paths = set()
        # 1. 存档目录内
        possible_paths.add(self.world_path / "usercache.json")
        # 2. 服务器根目录（存档的父目录）
        possible_paths.add(self.world_path.parent / "usercache.json")
        # 3. 向上查找 .minecraft 目录（支持版本隔离）
        current = self.world_path
        while len(current.parts) > 1:  # 避免无限循环
            if current.name == ".minecraft":
                possible_paths.add(current / "usercache.json")
                # 版本隔离目录
                versions_dir = current / "versions"
                if versions_dir.exists():
                    for version_dir in versions_dir.iterdir():
                        if version_dir.is_dir():
                            possible_paths.add(version_dir / "usercache.json")
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
        
        # 按顺序尝试所有可能的路径（第一个成功的将被使用）
        self._log(f"扫描 usercache.json 的可能路径: {possible_paths}", "IMPORT")
        for path in possible_paths:
            print(f"SCAN usercache: checking {path}")
            if path.exists():
                try:
                    import json
                    with open(path, "r", encoding="utf-8") as f:
                        entries = json.load(f)
                    imported = 0
                    for entry in entries:
                        uuid = entry.get("uuid", "").replace("-", "")
                        name = entry.get("name", "")
                        if uuid and name:
                            self._usercache[uuid] = name
                            imported += 1
                    self._log(f"从 {path.name} 加载了 {imported} 个用户缓存条目", "SCAN")
                    # 更新 player_names 缓存
                    updated = 0
                    for uuid in self._player_files.keys():
                        if uuid in self._usercache:
                            old = self._player_names.get(uuid)
                            self._player_names[uuid] = self._usercache[uuid]
                            updated += 1
                            self._log(f"自动更新玩家名称缓存: {uuid} -> {self._usercache[uuid]} (之前: {old})", "SCAN")
                    self._log(f"自动更新了 {updated} 个玩家名称缓存", "SCAN")
                    break  # 使用第一个找到的文件
                except Exception as e:
                    self._log(f"解析 usercache.json 失败: {e}", "WARNING")

    def _load_level_info(self) -> None:
        """读取 level.dat 并提取基础信息"""
        level_path = self.world_path / "level.dat"
        if not level_path.exists():
            self._log("未找到 level.dat", "WARNING")
            return
        try:
            self._level_data = nbtlib.load(level_path)
            root = self._level_data
            data = root.get("Data")
            if data is None:
                data = {}
            version = data.get("Version", {}).get("Id", 0) if data else 0
            version_name = data.get("Version", {}).get("Name", None) if data else None
            game_type = data.get("GameType", None) if data else None
            last_played = data.get("LastPlayed", None) if data else None
            spawn_x = data.get("SpawnX", None) if data else None
            spawn_y = data.get("SpawnY", None) if data else None
            spawn_z = data.get("SpawnZ", None) if data else None
            level_name = data.get("LevelName", None) if data else None
            self._world_info = WorldInfo(
                version=version,
                version_name=version_name,
                game_type=game_type,
                last_played=last_played,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                spawn_z=spawn_z,
                level_name=level_name,
            )
            self._log(f"已加载存档信息：版本 {version} ({version_name})", "INFO")
        except Exception as e:
            self._log(f"读取 level.dat 失败: {e}", "ERROR")

    def get_world_info(self) -> Optional[WorldInfo]:
        """返回已加载的世界信息"""
        return self._world_info

    def get_player_uuids(self) -> List[str]:
        """返回所有玩家的 UUID 列表"""
        return list(self._player_files.keys())

    def get_player_names(self) -> Dict[str, Optional[str]]:
        """返回 UUID 到玩家名称的映射（如未知则返回 None）"""
        print(f"GET_PLAYER_NAMES: usercache = {self._usercache}, player_files = {list(self._player_files.keys())}")
        for uuid in self._player_files:
            if uuid in self._player_names:
                continue
            # 尝试加载玩家数据提取名称
            data = self.get_player_data(uuid)
            if data is None:
                self._player_names[uuid] = None
                continue
            # 优先使用 usercache（可能更新）
            cached_name = self._usercache.get(uuid)
            if cached_name:
                self._player_names[uuid] = cached_name
                print(f"DEBUG: Using usercache name '{cached_name}' for {uuid}")
                continue
            # 尝试从常见标签提取玩家名称
            name = None
            # 常见标签列表（按优先级）
            possible_keys = [
                "LastKnownName",       # Bukkit/Spigot
                "Name",                # 原版？
                "bukkit.lastKnownName", # Bukkit 完整路径
                "CustomName",          # 自定义名称
                "display.Name",        # 显示名称
                "lastKnownName",       # 小写
                "name",                # 小写通用
            ]
            for key in possible_keys:
                tag = data.get(key)
                if tag is not None:
                    # 提取标签值
                    if hasattr(tag, 'value'):
                        name = str(tag.value)
                    else:
                        name = str(tag)
                    # 如果名称包含引号或特殊格式，清理
                    if name.startswith("'") and name.endswith("'"):
                        name = name[1:-1]
                    elif name.startswith('"') and name.endswith('"'):
                        name = name[1:-1]
                    break
            if name is not None:
                self._player_names[uuid] = name
                print(f"DEBUG: Found name '{name}' for {uuid} (from key)")
            else:
                self._player_names[uuid] = None
                # 调试：列出所有键以帮助诊断
                keys = list(data.keys())
                print(f"DEBUG: No name found for {uuid}, available keys: {keys}")
                # 尝试打印前几个键的值
                for key in keys[:5]:
                    tag = data.get(key)
                    tag_type = type(tag).__name__
                    print(f"  {key}: {tag_type}")
        return self._player_names.copy()

    def get_player_data(self, uuid: str) -> Optional[Compound]:
        """
        延迟加载指定 UUID 的玩家数据文件。

        Args:
            uuid: 玩家 UUID（不带扩展名）

        Returns:
            玩家数据的 NBT 标签，若加载失败则返回 None
        """
        norm_uuid = self._normalize_uuid(uuid)
        if norm_uuid in self._loaded_player_data:
            return self._loaded_player_data[norm_uuid]
        if norm_uuid not in self._player_files:
            self._log(f"玩家 UUID 不存在: {uuid} (规范后: {norm_uuid})", "WARNING")
            return None
        path = self._player_files[norm_uuid]
        try:
            data = nbtlib.load(path)
            self._loaded_player_data[norm_uuid] = data
            return data
        except Exception as e:
            self._log(f"加载玩家数据 {uuid} 失败: {e}", "ERROR")
            return None

    def get_player_inventory(self, uuid: str) -> List[Dict[str, Any]]:
        """
        提取指定玩家的背包物品列表。

        Args:
            uuid: 玩家 UUID

        Returns:
            物品字典列表，每项包含 slot, id, count, tag
        """
        data = self.get_player_data(uuid)
        if data is None:
            return []
        items: List[Dict[str, Any]] = []
        inventory = data.get("Inventory")
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

    def get_region(self, x: int, z: int) -> Optional[Path]:
        """
        获取指定坐标的区域文件路径（延迟加载仅为缓存路径）。

        Args:
            x, z: 区域坐标

        Returns:
            区域文件路径，若不存在则返回 None
        """
        if (x, z) in self._loaded_regions:
            return self._loaded_regions[(x, z)]
        if (x, z) not in self._region_files:
            self._log(f"区域文件不存在: r.{x}.{z}.mca", "WARNING")
            return None
        path = self._region_files[(x, z)]
        self._loaded_regions[(x, z)] = path
        return path

    def queue_modify_nbt(self, target: Union[Path, str], key_path: List[str], value: Any) -> None:
        """
        队列化一个 NBT 修改操作。

        Args:
            target: 目标文件路径或玩家 UUID
            key_path: 键路径列表，例如 ["Data", "Player", "Health"]
            value: 新值（必须是 NBT 兼容类型）
        """
        if isinstance(target, str):
            # 假设是玩家 UUID
            target_path = self._player_files.get(target)
            if target_path is None:
                self._log(f"无法找到玩家 {target} 的文件", "ERROR")
                return
            target = target_path
        action = Action(
            type='modify_nbt',
            target=target,
            data={'key_path': key_path, 'value': value},
        )
        self._action_queue.append(action)
        self._log(f"已队列化 NBT 修改: {key_path} -> {value}", "QUEUE")

    def queue_delete_region(self, x: int, z: int) -> None:
        """
        队列化删除指定区域文件的操作。

        Args:
            x, z: 区域坐标
        """
        if (x, z) not in self._region_files:
            self._log(f"区域文件不存在: r.{x}.{z}.mca", "WARNING")
            return
        action = Action(
            type='delete_region',
            target=(x, z),
        )
        self._action_queue.append(action)
        self._log(f"已队列化删除区域: r.{x}.{z}.mca", "QUEUE")

    def queue_rename_player(self, old_uuid: str, new_uuid: str) -> None:
        """
        队列化重命名玩家文件的操作。

        Args:
            old_uuid: 旧 UUID
            new_uuid: 新 UUID
        """
        if old_uuid not in self._player_files:
            self._log(f"玩家文件不存在: {old_uuid}", "WARNING")
            return
        action = Action(
            type='rename_player',
            target=(old_uuid, new_uuid),
        )
        self._action_queue.append(action)
        self._log(f"已队列化重命名玩家: {old_uuid} -> {new_uuid}", "QUEUE")

    def queue_custom(self, callback: Callable[[Path], Any]) -> None:
        """
        队列化一个自定义操作。

        Args:
            callback: 接受目标路径的回调函数
        """
        action = Action(
            type='custom',
            target=None,
            callback=callback,
        )
        self._action_queue.append(action)
        self._log("已队列化自定义操作", "QUEUE")

    def queue_conversion(self, target_platform: str = "java", target_version: Optional[int] = None) -> None:
        """
        队列化一个存档转换操作。
        
        Args:
            target_platform: 目标平台，"java" 或 "bedrock"
            target_version: 目标版本 ID（仅 Java 版有效）
        """
        def conversion_callback(target_world: Path) -> None:
            # 使用完整的转换管道
            try:
                from ..converter import convert_world
                success = convert_world(
                    src_path=target_world,
                    dst_path=target_world,  # 原地转换
                    target_platform=target_platform,
                    target_version=target_version
                )
                if success:
                    self._log(f"存档转换成功 (平台: {target_platform}, 版本: {target_version})", "SUCCESS")
                else:
                    self._log("存档转换失败", "ERROR")
            except Exception as e:
                self._log(f"转换过程发生错误: {e}", "ERROR")
        
        self.queue_custom(conversion_callback)
        self._log(f"已队列化转换操作到平台 {target_platform}", "QUEUE")

    def commit(self, dest_path: Optional[Path] = None, backup: bool = True) -> bool:
        """
        执行所有队列中的操作，并将结果写入目标路径。

        Args:
            dest_path: 目标存档路径，若为 None 则原地修改（强烈不建议）
            backup: 是否在修改前备份原存档

        Returns:
            成功返回 True，失败返回 False
        """
        if dest_path is None:
            self._log("警告：未提供目标路径，将原地修改（风险极高）", "WARNING")
            dest_path = self.world_path
        else:
            dest_path = dest_path.resolve()

        # 1. 备份
        if backup and dest_path == self.world_path:
            backup_dir = self.world_path.parent / f"{self.world_path.name}.backup"
            try:
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                shutil.copytree(self.world_path, backup_dir)
                self._log(f"已备份原存档到 {backup_dir}", "BACKUP")
            except Exception as e:
                self._log(f"备份失败: {e}", "ERROR")
                return False

        # 2. 克隆（如果目标路径与源路径不同）
        if dest_path != self.world_path:
            try:
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.copytree(self.world_path, dest_path)
                self._log(f"已克隆存档到 {dest_path}", "CLONE")
            except Exception as e:
                self._log(f"克隆失败: {e}", "ERROR")
                return False
            target_world = dest_path
        else:
            target_world = self.world_path

        # 3. 执行队列中的操作
        success = True
        for idx, action in enumerate(self._action_queue):
            try:
                self._execute_action(action, target_world)
                self._log(f"操作 {idx+1}/{len(self._action_queue)} 执行成功", "ACTION")
            except Exception as e:
                self._log(f"操作 {idx+1} 执行失败: {e}", "ERROR")
                success = False

        # 4. 清空队列
        if success:
            self._action_queue.clear()
            self._log("所有操作已提交", "COMMIT")
        else:
            self._log("部分操作失败，队列未清空", "ERROR")
        return success

    def _execute_action(self, action: Action, target_world: Path) -> None:
        """执行单个操作"""
        if action.type == 'modify_nbt':
            self._execute_modify_nbt(action, target_world)
        elif action.type == 'delete_region':
            self._execute_delete_region(action, target_world)
        elif action.type == 'rename_player':
            self._execute_rename_player(action, target_world)
        elif action.type == 'custom' and action.callback:
            action.callback(target_world)
        else:
            raise ValueError(f"未知操作类型: {action.type}")

    def _execute_modify_nbt(self, action: Action, target_world: Path) -> None:
        """执行 NBT 修改"""
        target_path = action.target
        if isinstance(target_path, str):
            # 玩家 UUID，需要转换为实际路径
            target_path = target_world / "playerdata" / f"{target_path}.dat"
        elif isinstance(target_path, Path):
            # 确保路径相对于目标世界
            if not target_path.is_absolute():
                target_path = target_world / target_path
        else:
            target_path = Path(target_path)
        key_path = action.data['key_path']
        value = action.data['value']

        # 加载 NBT
        data = nbtlib.load(target_path)
        # 递归查找目标键
        node = data
        for key in key_path[:-1]:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                raise KeyError(f"键路径 {key_path} 不存在于 {target_path}")
        last_key = key_path[-1]
        if isinstance(node, dict) and last_key in node:
            node[last_key] = value
        else:
            raise KeyError(f"最终键 {last_key} 不存在")
        # 保存
        data.save()

    def _execute_delete_region(self, action: Action, target_world: Path) -> None:
        """删除区域文件"""
        x, z = action.target
        # 查找目标世界中的区域文件
        pattern = f"region/r.{x}.{z}.mca"
        for f in target_world.rglob(pattern):
            f.unlink(missing_ok=True)
            break
        # 同时删除 DIM* 下的区域文件
        for dim in target_world.glob("DIM*"):
            region_file = dim / "region" / f"r.{x}.{z}.mca"
            if region_file.exists():
                region_file.unlink(missing_ok=True)

    def _execute_rename_player(self, action: Action, target_world: Path) -> None:
        """重命名玩家文件"""
        old_uuid, new_uuid = action.target
        for folder in ["playerdata", "stats", "advancements"]:
            folder_path = target_world / folder
            if not folder_path.exists():
                continue
            for old_file in folder_path.glob(f"{old_uuid}*"):
                new_name = old_file.name.replace(old_uuid, new_uuid)
                new_path = folder_path / new_name
                if new_path.exists():
                    new_path.unlink(missing_ok=True)
                old_file.rename(new_path)

    def import_usercache(self, path: Path) -> int:
        """
        从指定的 usercache.json 文件导入玩家名称映射。

        Args:
            path: usercache.json 文件路径

        Returns:
            成功导入的条目数量
        """
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                entries = json.load(f)
            imported = 0
            for entry in entries:
                uuid = entry.get("uuid", "").replace("-", "")
                name = entry.get("name", "")
                if uuid and name:
                    self._usercache[uuid] = name
                    imported += 1
            self._log(f"从 {path.name} 导入了 {imported} 个玩家名称", "IMPORT")
            self._log(f"导入后 usercache 内容: {self._usercache}", "IMPORT")
            self._log(f"当前 player_names 键: {list(self._player_names.keys())}", "IMPORT")
            # 为所有在 player_files 中的 UUID 更新 player_names
            updated = 0
            for uuid in self._player_files.keys():
                if uuid in self._usercache:
                    old = self._player_names.get(uuid)
                    self._player_names[uuid] = self._usercache[uuid]
                    updated += 1
                    self._log(f"更新玩家名称缓存: {uuid} -> {self._usercache[uuid]} (之前: {old})", "IMPORT")
            self._log(f"更新了 {updated} 个玩家名称缓存", "IMPORT")
            return imported
        except Exception as e:
            self._log(f"导入 usercache.json 失败: {e}", "ERROR")
            return 0

    def get_queue_size(self) -> int:
        """返回队列中待执行的操作数量"""
        return len(self._action_queue)

    def clear_queue(self) -> None:
        """清空操作队列"""
        self._action_queue.clear()
        self._log("操作队列已清空", "QUEUE")