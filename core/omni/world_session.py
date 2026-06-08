"""
存档会话管理 (WorldSession)

实现非破坏性、延迟加载机制，支持任务队列与统一提交。
"""
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable, Union
from dataclasses import dataclass
import nbtlib
from nbtlib import Compound, File
from ..scanner import scan_all_regions
from ..types import LogCallback
from ..utils import replace_directory_tree


@dataclass
class WorldInfo:
    """从 level.dat 提取的完整信息"""
    version: int
    version_name: Optional[str] = None
    game_type: Optional[int] = None
    last_played: Optional[int] = None
    spawn_x: Optional[int] = None
    spawn_y: Optional[int] = None
    spawn_z: Optional[int] = None
    level_name: Optional[str] = None
    difficulty: Optional[int] = None
    hardcore: Optional[bool] = None
    allow_commands: Optional[bool] = None
    seed: Optional[int] = None
    day_time: Optional[int] = None
    time: Optional[int] = None
    rain_time: Optional[int] = None
    raining: Optional[bool] = None
    thunder_time: Optional[int] = None
    thundering: Optional[bool] = None
    version_series: Optional[str] = None
    version_snapshot: Optional[bool] = None
    data_packs: Optional[Dict[str, List[str]]] = None
    server_brands: Optional[List[str]] = None
    was_modded: Optional[bool] = None
    clear_weather_time: Optional[int] = None
    initialized: Optional[bool] = None


@dataclass
class Action:
    """代表一个待执行的操作"""
    type: str  # 'modify_nbt', 'delete_region', 'rename_player', 'custom', 'modify_chunk'
    target: Any  # 文件路径、坐标、UUID 等
    data: Any = None
    callback: Optional[Callable] = None


@dataclass
class ChunkTarget:
    """区块编辑目标"""
    region_path: Path  # 相对存档根目录的路径
    chunk_x: int
    chunk_z: int
    full_chunk_data: Any  # 完整的区块 NBT 数据


class WorldSession:
    """存档会话管理器，提供延迟加载与任务队列"""

    def __init__(
            self,
            world_path: Path,
            log: Optional[LogCallback] = None) -> None:
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

        from core.performance import get_tracker
        tracker = get_tracker()
        with tracker.track("存档加载", {"world": self.world_path.name}):
            self._scan_files()
            self._load_level_info()
            tracker.add_metadata("players", len(self._player_files))
            tracker.add_metadata("regions", len(self._region_files))

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
        # 扫描 playerdata（iterdir 比 glob 略快）
        playerdata_dir = self.world_path / "playerdata"
        if playerdata_dir.is_dir():
            try:
                for f in playerdata_dir.iterdir():
                    if f.is_file() and f.suffix == ".dat":
                        uuid = self._normalize_uuid(f.stem)
                        self._player_files[uuid] = f
            except OSError:
                pass
        self._log(f"发现 {len(self._player_files)} 个玩家数据文件", "SCAN")

        # 初始化 player_names（先从 usercache 收集后会继续完善）
        for uuid in self._player_files:
            if uuid not in self._player_names:
                self._player_names[uuid] = None

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
        if data_dir.is_dir():
            try:
                self._data_files = list(data_dir.glob("*.dat"))
            except OSError:
                pass
        self._log(f"发现 {len(self._data_files)} 个数据文件", "SCAN")

        # 扫描 usercache.json（限制搜索深度，避免遍历版本目录）
        import json
        player_set = set(self._player_files.keys())
        best_cache: Dict[str, str] = {}
        best_match = -1

        # 仅检查有限的候选路径，不遍历 versions/ 子目录
        candidate_paths: List[Path] = []
        candidate_paths.append(self.world_path / "usercache.json")
        candidate_paths.append(self.world_path.parent / "usercache.json")
        # 向上查找 .minecraft（最多 5 层）
        current = self.world_path
        for _ in range(5):
            parent = current.parent
            if parent == current:
                break
            if parent.name == ".minecraft":
                candidate_paths.append(parent / "usercache.json")
                break
            current = parent

        for path in candidate_paths:
            if not path.is_file():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entries = json.load(f)
                cache_map: Dict[str, str] = {}
                match_count = 0
                for entry in entries:
                    uuid = entry.get("uuid", "").replace("-", "")
                    name = entry.get("name", "")
                    if uuid and name:
                        cache_map[uuid] = name
                        if uuid in player_set:
                            match_count += 1
                self._log(
                    f"候选 usercache: {path}, 匹配 {match_count}/{len(player_set)}", "IMPORT")
                if match_count > best_match:
                    best_match = match_count
                    best_cache = cache_map
                if match_count == len(player_set):
                    break  # 完美匹配，提前退出
            except Exception as e:
                self._log(f"解析 usercache {path} 失败: {e}", "WARNING")

        if best_cache:
            self._usercache = best_cache
            for uuid in self._player_files:
                if uuid in self._usercache:
                    self._player_names[uuid] = self._usercache[uuid]
            self._log(f"已从 usercache 更新 {best_match} 个玩家名称", "SCAN")

    def _load_level_info(self) -> None:
        """读取 level.dat 并提取完整信息"""
        level_path = self.world_path / "level.dat"
        if not level_path.exists():
            self._log("未找到 level.dat，这可能不是有效的 Minecraft 存档目录", "WARNING")
            raise FileNotFoundError(f"未找到 level.dat: {level_path}")
        try:
            self._level_data = nbtlib.load(level_path)
            root = self._level_data
            data = root.get("Data")
            if data is None:
                data = {}
            version = data.get("Version", {}).get("Id", 0) if data else 0
            version_name = data.get(
                "Version", {}).get(
                "Name", None) if data else None
            game_type = data.get("GameType", None) if data else None
            last_played = data.get("LastPlayed", None) if data else None
            spawn_x = data.get("SpawnX", None) if data else None
            spawn_y = data.get("SpawnY", None) if data else None
            spawn_z = data.get("SpawnZ", None) if data else None
            level_name = data.get("LevelName", None) if data else None
            difficulty = data.get("Difficulty", None) if data else None
            hardcore = data.get("hardcore", None) if data else None
            allow_commands = data.get("allowCommands", None) if data else None
            day_time = data.get("DayTime", None) if data else None
            time = data.get("Time", None) if data else None
            rain_time = data.get("rainTime", None) if data else None
            raining = data.get("raining", None) if data else None
            thunder_time = data.get("thunderTime", None) if data else None
            thundering = data.get("thundering", None) if data else None
            version_series = data.get(
                "Version", {}).get(
                "Series", None) if data else None
            version_snapshot = data.get(
                "Version", {}).get(
                "Snapshot", None) if data else None
            server_brands = data.get("ServerBrands", None) if data else None
            was_modded = data.get("WasModded", None) if data else None
            clear_weather_time = data.get(
                "clearWeatherTime", None) if data else None
            initialized = data.get("initialized", None) if data else None

            seed = None
            if data:
                wgs = data.get("WorldGenSettings")
                if wgs:
                    seed = wgs.get("seed", None)

            data_packs = None
            if data:
                dp = data.get("DataPacks")
                if dp:
                    enabled = dp.get("Enabled", [])
                    disabled = dp.get("Disabled", [])
                    if enabled or disabled:
                        data_packs = {
                            "enabled": [
                                str(e) for e in enabled] if enabled else [], "disabled": [
                                str(d) for d in disabled] if disabled else [], }

            self._world_info = WorldInfo(
                version=version,
                version_name=version_name,
                game_type=game_type,
                last_played=last_played,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
                spawn_z=spawn_z,
                level_name=level_name,
                difficulty=difficulty,
                hardcore=hardcore,
                allow_commands=allow_commands,
                seed=seed,
                day_time=day_time,
                time=time,
                rain_time=rain_time,
                raining=raining,
                thunder_time=thunder_time,
                thundering=thundering,
                version_series=version_series,
                version_snapshot=version_snapshot,
                data_packs=data_packs,
                server_brands=server_brands,
                was_modded=was_modded,
                clear_weather_time=clear_weather_time,
                initialized=initialized,
            )
            self._log(f"已加载存档信息：版本 {version} ({version_name})", "INFO")
        except Exception as e:
            self._log(f"解析 level.dat 失败: {type(e).__name__}: {e}", "ERROR")
            raise RuntimeError(
                f"NBT 解析失败 ({
                    level_path.name}): {
                    type(e).__name__}: {e}") from e

    def get_world_info(self) -> Optional[WorldInfo]:
        """返回已加载的世界信息"""
        return self._world_info

    def get_player_uuids(self) -> List[str]:
        """返回所有玩家的 UUID 列表"""
        return list(self._player_files.keys())

    def get_player_names(self) -> Dict[str, Optional[str]]:
        """返回 UUID 到玩家名称的映射。

        仅返回已从 usercache.json 缓存的名称，不加载 NBT 文件。
        未知名称返回 None，可通过 resolve_player_name() 按需加载。
        """
        result: Dict[str, Optional[str]] = {}
        for uuid in self._player_files:
            result[uuid] = self._player_names.get(uuid)
        return result

    def resolve_player_name(self, uuid: str) -> Optional[str]:
        """按需解析单个玩家名称（加载 NBT）。

        Args:
            uuid: 玩家 UUID

        Returns:
            玩家名称，若无法解析则返回 None
        """
        norm = self._normalize_uuid(uuid)
        if norm in self._player_names and self._player_names[norm] is not None:
            return self._player_names[norm]
        data = self.get_player_data(norm)
        if data is None:
            return None
        for key in ("LastKnownName", "Name", "bukkit.lastKnownName",
                    "CustomName", "display.Name", "lastKnownName", "name"):
            tag = data.get(key)
            if tag is not None:
                name = str(tag.value) if hasattr(tag, 'value') else str(tag)
                name = name.strip("'\"")
                self._player_names[norm] = name
                return name
        return None

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

    def load_player_data(self, uuid: str) -> Optional[Compound]:
        """
        加载指定玩家的完整 NBT 数据（供 ExplorerView 使用）。

        Args:
            uuid: 玩家 UUID

        Returns:
            玩家 NBT 数据，若加载失败则返回 None
        """
        return self.get_player_data(uuid)

    def load_player_nbt(self, uuid: str) -> Optional[Compound]:
        """
        加载指定玩家的完整 NBT 数据（供 NBT 查看器使用）。

        Args:
            uuid: 玩家 UUID

        Returns:
            玩家 NBT 数据，若加载失败则返回 None
        """
        return self.get_player_data(uuid)

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

    def queue_modify_nbt(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        """
        队列化一个 NBT 修改操作。

        Args:
            target: 目标文件路径或玩家 UUID
            key_path: 键路径列表，例如 ["Data", "Player", "Health"]
            value: 新值（必须是 NBT 兼容类型）
        """
        if isinstance(target, str) and (target.endswith(
                ".dat") or "/" in target or "\\" in target):
            target = Path(target)
        elif isinstance(target, str):
            norm_target = self._normalize_uuid(target)
            target_path = self._player_files.get(norm_target)
            if target_path is None:
                self._log(f"无法找到玩家 {target} 的文件", "ERROR")
                return
            target = target_path
        if isinstance(target, Path) and target.is_absolute():
            try:
                target = target.relative_to(self.world_path)
            except ValueError:
                pass
        action = Action(
            type='modify_nbt',
            target=target,
            data={
                'key_path': key_path,
                'value': value,
                'operation': operation},
        )
        self._action_queue.append(action)
        self._log(f"已队列化 NBT {operation}: {key_path} -> {value}", "QUEUE")

    def queue_modify_json(
        self,
        target: Union[Path, str],
        key_path: List[Union[str, int]],
        value: Any,
        operation: str = "set",
    ) -> None:
        if isinstance(target, str):
            target = Path(target)
        if isinstance(target, Path) and target.is_absolute():
            try:
                target = target.relative_to(self.world_path)
            except ValueError:
                pass
        action = Action(
            type='modify_json',
            target=target,
            data={
                'key_path': key_path,
                'value': value,
                'operation': operation},
        )
        self._action_queue.append(action)
        self._log(f"已队列化 JSON {operation}: {key_path} -> {value}", "QUEUE")

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

    def queue_conversion(
            self,
            target_platform: str = "java",
            target_version: Optional[int] = None) -> None:
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
                    self._log(
                        f"存档转换成功 (平台: {target_platform}, 版本: {target_version})",
                        "SUCCESS")
                else:
                    self._log("存档转换失败", "ERROR")
            except Exception as e:
                self._log(f"转换过程发生错误: {e}", "ERROR")

        self.queue_custom(conversion_callback)
        self._log(f"已队列化转换操作到平台 {target_platform}", "QUEUE")

    def commit(
            self,
            dest_path: Optional[Path] = None,
            backup: bool = True) -> bool:
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
            backup_dir = self.world_path.parent / \
                f"{self.world_path.name}.backup"
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
                replace_directory_tree(self.world_path, dest_path)
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
                self._log(
                    f"操作 {idx + 1}/{len(self._action_queue)} 执行成功", "ACTION")
            except Exception as e:
                self._log(f"操作 {idx + 1} 执行失败: {e}", "ERROR")
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
        elif action.type == 'modify_json':
            self._execute_modify_json(action, target_world)
        elif action.type == 'modify_chunk':
            self._execute_modify_chunk(action, target_world)
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
        target_path = target_path.resolve()
        target_root = target_world.resolve()
        try:
            target_path.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"拒绝修改存档目录外的 NBT 文件: {target_path}") from exc
        key_path = action.data['key_path']
        value = action.data['value']
        operation = action.data.get('operation', 'set')

        # 加载 NBT
        data = nbtlib.load(target_path)
        self._apply_path_operation(
            data,
            key_path,
            value,
            operation,
            f"NBT 文件 {target_path}")
        # 保存
        data.save()

    def _resolve_world_file(self, target: Any, target_world: Path) -> Path:
        target_path = target
        if isinstance(target_path, str):
            target_path = Path(target_path)
        elif not isinstance(target_path, Path):
            target_path = Path(target_path)
        if not target_path.is_absolute():
            target_path = target_world / target_path
        target_path = target_path.resolve()
        target_root = target_world.resolve()
        try:
            target_path.relative_to(target_root)
        except ValueError as exc:
            raise ValueError(f"拒绝修改存档目录外的文件: {target_path}") from exc
        return target_path

    def _execute_modify_json(self, action: Action, target_world: Path) -> None:
        target_path = self._resolve_world_file(action.target, target_world)
        key_path = action.data['key_path']
        value = action.data['value']
        operation = action.data.get('operation', 'set')
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._apply_path_operation(
            data,
            key_path,
            value,
            operation,
            f"JSON 文件 {target_path}")
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _apply_path_operation(
        self,
        data: Any,
        key_path: List[Union[str, int]],
        value: Any,
        operation: str,
        context: str,
    ) -> None:
        if not key_path:
            raise KeyError(f"{context} 的路径不能为空")
        node = data
        for key in key_path[:-1]:
            if isinstance(
                    key,
                    int) and isinstance(
                    node,
                    list) and 0 <= key < len(node):
                node = node[key]
            elif isinstance(key, str) and isinstance(node, dict) and key in node:
                node = node[key]
            else:
                raise KeyError(f"路径 {key_path} 不存在于 {context}")
        last_key = key_path[-1]
        if isinstance(last_key, int) and isinstance(node, list):
            if operation == "add":
                if last_key < 0 or last_key > len(node):
                    raise IndexError(f"列表插入位置越界: {last_key}")
                if last_key == len(node):
                    node.append(value)
                else:
                    node.insert(last_key, value)
            elif operation == "delete":
                if last_key < 0 or last_key >= len(node):
                    raise IndexError(f"列表删除位置越界: {last_key}")
                del node[last_key]
            else:
                if last_key < 0 or last_key >= len(node):
                    raise IndexError(f"列表修改位置越界: {last_key}")
                node[last_key] = value
        elif isinstance(last_key, str) and isinstance(node, dict):
            if operation == "add":
                if last_key in node:
                    raise KeyError(f"字段已存在: {last_key}")
                node[last_key] = value
            elif operation == "delete":
                if last_key not in node:
                    raise KeyError(f"字段不存在: {last_key}")
                del node[last_key]
            else:
                if last_key not in node:
                    raise KeyError(f"字段不存在: {last_key}")
                node[last_key] = value
        else:
            raise KeyError(f"路径 {key_path} 无法应用到 {context}")

    def _execute_delete_region(
            self,
            action: Action,
            target_world: Path) -> None:
        """删除区域文件"""
        x, z = action.target
        # 只删除标准 region 目录下的文件
        region_file = target_world / "region" / f"r.{x}.{z}.mca"
        if region_file.exists():
            region_file.unlink(missing_ok=True)
        # 同时删除 DIM* 下的区域文件
        for dim in target_world.glob("DIM*"):
            region_file = dim / "region" / f"r.{x}.{z}.mca"
            if region_file.exists():
                region_file.unlink(missing_ok=True)

    def _execute_rename_player(
            self,
            action: Action,
            target_world: Path) -> None:
        """重命名玩家文件"""
        old_uuid, new_uuid = action.target
        for folder in ["playerdata", "stats", "advancements"]:
            folder_path = target_world / folder
            if not folder_path.exists():
                continue
            for old_file in folder_path.glob(f"{old_uuid}*"):
                # 使用精确匹配替换，避免误替换
                suffix = old_file.name[len(old_uuid):]
                new_name = f"{new_uuid}{suffix}"
                new_path = folder_path / new_name
                if new_path.exists():
                    self._log(
                        f"跳过玩家文件重命名冲突: {
                            old_file.name} -> {new_name}",
                        "WARN")
                    continue
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

            # 为所有在 player_files 中的 UUID 更新 player_names
            updated = 0
            for uuid in self._player_files.keys():
                if uuid in self._usercache:
                    old = self._player_names.get(uuid)
                    self._player_names[uuid] = self._usercache[uuid]
                    updated += 1
                    self._log(
                        f"更新玩家名称: {uuid} -> {self._usercache[uuid]} (之前: {old})", "IMPORT")
            self._log(f"更新了 {updated} 个玩家名称", "IMPORT")
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

    def get_dimensions(self) -> List[Dict[str, str]]:
        """
        扫描存档中所有可用的维度目录。

        利用已缓存的 _region_files 避免重复 glob 扫描。

        Returns:
            维度信息列表，每项包含 id, name, region_dir
        """
        dimensions: List[Dict[str, str]] = []
        seen: set = set()

        # 构建已有 region 文件的父目录集合，用于快速判断维度是否存在
        region_parent_dirs: set = set()
        for p in self._region_files.values():
            region_parent_dirs.add(p.parent)

        def _has_regions(region_dir: Path) -> bool:
            return region_dir in region_parent_dirs

        vanilla_dims = [
            ("overworld", "🌍 主世界", self.world_path / "region"),
            ("nether", "🔥 下界", self.world_path / "DIM-1" / "region"),
            ("end", "🌌 末地", self.world_path / "DIM1" / "region"),
        ]
        for dim_id, dim_name, region_dir in vanilla_dims:
            if _has_regions(region_dir):
                dimensions.append(
                    {"id": dim_id, "name": dim_name, "region_dir": str(region_dir)})
                seen.add(dim_id)

        # DIM* 格式（旧版模组维度）
        try:
            for dim_dir in self.world_path.iterdir():
                if not dim_dir.is_dir() or not dim_dir.name.startswith("DIM"):
                    continue
                if dim_dir.name in ("DIM-1", "DIM1"):
                    continue
                region_dir = dim_dir / "region"
                dim_id = dim_dir.name.lower()
                if dim_id not in seen and _has_regions(region_dir):
                    dimensions.append({
                        "id": dim_id,
                        "name": f"📦 {dim_dir.name}",
                        "region_dir": str(region_dir),
                    })
                    seen.add(dim_id)
        except OSError:
            pass

        # dimensions/{namespace}/{name} 格式（1.16+ 模组维度）
        dimensions_base = self.world_path / "dimensions"
        if dimensions_base.is_dir():
            try:
                for namespace_dir in dimensions_base.iterdir():
                    if not namespace_dir.is_dir():
                        continue
                    try:
                        for dim_dir in namespace_dir.iterdir():
                            if not dim_dir.is_dir():
                                continue
                            region_dir = dim_dir / "region"
                            if not _has_regions(region_dir):
                                continue
                            namespace = namespace_dir.name
                            dim_name_str = dim_dir.name
                            dim_id = f"{namespace}:{dim_name_str}"
                            if dim_id in seen:
                                continue
                            display_name = f"📦 {namespace}:{dim_name_str}"
                            if namespace == "minecraft":
                                vanilla_map = {
                                    "overworld": "🌍 主世界",
                                    "the_nether": "🔥 下界",
                                    "the_end": "🌌 末地",
                                }
                                display_name = vanilla_map.get(
                                    dim_name_str, display_name)
                            dimensions.append({
                                "id": dim_id,
                                "name": display_name,
                                "region_dir": str(region_dir),
                            })
                            seen.add(dim_id)
                    except OSError:
                        pass
            except OSError:
                pass

        self._log(f"发现 {len(dimensions)} 个维度", "SCAN")
        return dimensions

    def create_backup(
            self,
            backup_name: Optional[str] = None) -> Optional[Path]:
        """
        创建当前存档的备份。

        Args:
            backup_name: 备份名称，若为 None 则使用时间戳

        Returns:
            备份文件夹路径，失败返回 None
        """
        import datetime
        try:
            if backup_name is None:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_name = f"{self.world_path.name}_backup_{timestamp}"
            backup_dir = self.world_path.parent / backup_name
            if backup_dir.exists():
                # 清理旧备份
                try:
                    shutil.rmtree(backup_dir)
                except Exception as e:
                    self._log(f"清理旧备份失败: {e}", "WARNING")
                    # 尝试使用带后缀的名称
                    i = 1
                    while (
                            self.world_path.parent /
                            f"{backup_name}_{i}").exists():
                        i += 1
                    backup_dir = self.world_path.parent / f"{backup_name}_{i}"
            shutil.copytree(self.world_path, backup_dir)
            self._log(f"已创建备份: {backup_dir}", "BACKUP")
            return backup_dir
        except Exception as e:
            self._log(f"创建备份失败: {e}", "ERROR")
            return None

    def restore_backup(
            self,
            backup_path: Path,
            replace_current: bool = False) -> bool:
        """
        从备份恢复存档。

        Args:
            backup_path: 备份文件夹路径
            replace_current: 是否替换当前存档（危险操作）

        Returns:
            是否成功
        """
        try:
            if not backup_path.exists() or not backup_path.is_dir():
                self._log(f"备份不存在或不是目录: {backup_path}", "ERROR")
                return False
            if replace_current:
                # 先备份当前存档
                current_backup = self.create_backup(
                    f"{self.world_path.name}_pre_restore")
                if current_backup is None:
                    self._log("无法在恢复前备份当前存档，取消恢复", "ERROR")
                    return False
                # 删除当前存档
                shutil.rmtree(self.world_path)
                # 从备份复制
                shutil.copytree(backup_path, self.world_path)
                self._log(f"已从备份恢复存档: {backup_path}", "RESTORE")
                return True
            else:
                # 创建副本而不替换当前存档
                dest_name = f"{self.world_path.name}_restored"
                dest_path = self.world_path.parent / dest_name
                i = 1
                while dest_path.exists():
                    dest_path = self.world_path.parent / f"{dest_name}_{i}"
                    i += 1
                shutil.copytree(backup_path, dest_path)
                self._log(f"已将备份恢复到: {dest_path}", "RESTORE")
                return True
        except Exception as e:
            self._log(f"恢复备份失败: {e}", "ERROR")
            return False

    def list_backups(self) -> List[Path]:
        """
        列出当前存档的所有备份。

        Returns:
            备份文件夹路径列表
        """
        backups = []
        try:
            parent_dir = self.world_path.parent
            world_name = self.world_path.name
            for item in parent_dir.iterdir():
                if item.is_dir() and item.name.startswith(world_name) and (
                        "backup" in item.name or "restored" in item.name):
                    backups.append(item)
            # 按修改时间排序，最新的在前
            backups.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        except Exception as e:
            self._log(f"列出备份失败: {e}", "ERROR")
        return backups

    def load_chunk_nbt(self, region_path: Path, chunk_x: int,
                       chunk_z: int) -> Optional[Tuple[Any, Path]]:
        """
        加载指定区块的 NBT 数据

        Args:
            region_path: 相对存档根目录的区域文件路径
            chunk_x: 区块在区域内的 X 坐标 (0-31)
            chunk_z: 区块在区域内的 Z 坐标 (0-31)

        Returns:
            (区块数据, 绝对路径) 或 None
        """
        try:
            abs_region_path = self.world_path / region_path
            if not abs_region_path.exists():
                self._log(f"区域文件不存在: {region_path}", "ERROR")
                return None

            from anvil import Region
            region = Region.from_file(str(abs_region_path))
            chunk = region.get_chunk(chunk_x, chunk_z)

            if chunk is None or not hasattr(chunk, "data"):
                self._log(
                    f"区块数据不存在: {region_path} [{chunk_x}, {chunk_z}]",
                    "WARNING")
                return None

            self._log(f"已加载区块: {region_path} [{chunk_x}, {chunk_z}]", "INFO")
            return chunk.data, abs_region_path
        except Exception as e:
            self._log(f"加载区块失败: {e}", "ERROR")
            return None

    def queue_modify_chunk(
            self,
            region_path: Path,
            chunk_x: int,
            chunk_z: int,
            full_chunk_data: Any) -> None:
        """
        队列化区块修改操作

        Args:
            region_path: 相对存档根目录的区域文件路径
            chunk_x: 区块在区域内的 X 坐标 (0-31)
            chunk_z: 区块在区域内的 Z 坐标 (0-31)
            full_chunk_data: 修改后的完整区块 NBT 数据
        """
        target = ChunkTarget(
            region_path=region_path,
            chunk_x=chunk_x,
            chunk_z=chunk_z,
            full_chunk_data=full_chunk_data
        )
        action = Action(
            type="modify_chunk",
            target=target,
            data=None
        )
        self._action_queue.append(action)
        self._log(f"已队列化区块修改: {region_path} [{chunk_x}, {chunk_z}]", "QUEUE")

    def _execute_modify_chunk(
            self,
            action: Action,
            target_world: Path) -> None:
        """执行区块修改操作"""
        target = action.target
        if not isinstance(target, ChunkTarget):
            raise ValueError("无效的区块目标")

        abs_region_path = target_world / target.region_path
        if not abs_region_path.exists():
            raise ValueError(f"区域文件不存在: {target.region_path}")

        # 备份区域文件
        from app.services.region_editor_service import get_region_editor_service
        editor = get_region_editor_service(log=self.log)
        editor._backup_region(abs_region_path, backup=True)

        # 写入区块
        self._write_chunk(
            abs_region_path,
            target.chunk_x,
            target.chunk_z,
            target.full_chunk_data)
        self._log(
            f"已写回区块: {
                target.region_path} [{
                target.chunk_x}, {
                target.chunk_z}]",
            "SAVE")

    def _write_chunk(
            self,
            region_path: Path,
            chunk_x: int,
            chunk_z: int,
            chunk_data: Any) -> None:
        """将区块数据写回区域文件"""
        try:
            from app.services.region_editor_service import get_region_editor_service
            editor = get_region_editor_service(log=self.log)
            import io
            import zlib

            buffer = io.BytesIO()
            if hasattr(chunk_data, "write_file"):
                chunk_data.write_file(buffer=buffer)
            elif hasattr(chunk_data, "write"):
                chunk_data.write(buffer)
            elif hasattr(chunk_data, "save"):
                chunk_data.save(buffer, gzipped=False)
            else:
                raise TypeError(
                    f"不支持的区块 NBT 对象类型: {
                        type(chunk_data).__name__}")
            nbt_bytes = buffer.getvalue()
            compressed = zlib.compress(nbt_bytes, 6)
            length = len(compressed) + 1
            chunk_record = length.to_bytes(4, "big") + b"\x02" + compressed
            editor._write_chunk_record(
                region_path, chunk_x, chunk_z, chunk_record)
        except Exception as e:
            self._log(f"写回区块失败: {e}", "ERROR")
            raise
